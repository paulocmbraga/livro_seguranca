"""Ataque calibrado e três ajustes epsilon-DP com contador real da biblioteca."""
from pathlib import Path
import warnings
import numpy as np
from scipy.special import expit
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from diffprivlib.models import LogisticRegression as PrivateLogistic
from diffprivlib.accountant import BudgetAccountant, BudgetError
from .common import new_output, write, read, seal, integrity

EPSILONS = (.5, 2., 8.)
DIM = 80


def data():
    rng = np.random.default_rng(2501)
    x = rng.uniform(-1, 1, (560, DIM))
    y = (x[:, 0] + .6*x[:, 1] + rng.normal(0,.7,560) > 0).astype(int)
    return {'x':x.tolist(), 'y':y.tolist(), 'train':list(range(160)),
            'cal_members':list(range(80)), 'eval_members':list(range(80,160)),
            'cal_nonmembers':list(range(160,240)), 'eval_nonmembers':list(range(240,320)),
            'utility':list(range(320,560))}


def check_domain(x):
    x = np.asarray(x)
    if x.ndim != 2 or x.shape[1] != DIM or not np.isfinite(x).all() or np.abs(x).max() > 1:
        raise ValueError('domínio público [-1,1]^80 violado')


def metrics(member_scores, nonmember_scores, threshold):
    a, b = np.asarray(member_scores), np.asarray(nonmember_scores)
    if not len(a) or not len(b): raise ValueError('denominador vazio')
    tp, fp = int(sum(a >= threshold)), int(sum(b >= threshold))
    tpr, fpr = tp/len(a), fp/len(b)
    denominator = .01*tpr + .99*fpr
    return {'members':len(a),'nonmembers':len(b),'tp':tp,'fn':len(a)-tp,'fp':fp,'tn':len(b)-fp,
            'tpr':tpr,'fpr':fpr,'advantage':tpr-fpr,'balanced_accuracy':(1+tpr-fpr)/2,
            'auc':float(roc_auc_score([1]*len(a)+[0]*len(b), np.r_[a,b])),
            'ppv_prior_1pct':.01*tpr/denominator if denominator else None}


def choose_threshold(a, b):
    # Empate: limiar mais alto; apenas a calibração entra nesta função.
    candidates = np.r_[a, b, 1.0000001]
    return float(max(candidates, key=lambda t:(metrics(a,b,t)['advantage'], t)))


def summarize(scores, d):
    y = np.asarray(d['y'])
    truth_scores = np.where(y == 1, scores, 1-scores)
    threshold = choose_threshold(truth_scores[d['cal_members']], truth_scores[d['cal_nonmembers']])
    indices = d['utility']
    return {'threshold':threshold,
            'calibration':metrics(truth_scores[d['cal_members']],truth_scores[d['cal_nonmembers']],threshold),
            'evaluation':metrics(truth_scores[d['eval_members']],truth_scores[d['eval_nonmembers']],threshold),
            'utility_n':len(indices),'utility_correct':int(sum((scores[indices]>=.5)==y[indices]))}


def run(directory):
    out = new_output(directory); d = data(); write(out/'data.json',d)
    x,y = np.asarray(d['x']),np.asarray(d['y']); check_domain(x)
    acc = BudgetAccountant(epsilon=sum(EPSILONS),delta=0,slack=0)
    results = []
    for eps in (None,)+EPSILONS:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            if eps is None: model = LogisticRegression(C=10,max_iter=1000)
            else: model = PrivateLogistic(epsilon=eps,data_norm=np.sqrt(DIM),C=10,
                                          max_iter=1000,random_state=None,accountant=acc)
            model.fit(x[d['train']],y[d['train']])
        scores = model.predict_proba(x)[:,1]
        key = 'nonprivate' if eps is None else 'epsilon_'+str(eps)
        coefficients = {'coef':model.coef_[0].tolist(),'intercept':float(model.intercept_[0])}
        write(out/(key+'_model.json'),coefficients)
        results.append({'id':key,'epsilon':eps,'scores':scores.tolist(),**summarize(scores,d),
                        'warnings':[str(w.message) for w in caught], 'accountant':list(acc.total())})
    blocked = False
    try:
        PrivateLogistic(epsilon=.1,data_norm=np.sqrt(DIM),accountant=acc).fit(x[:160],y[:160])
    except BudgetError: blocked = True
    write(out/'results.json',results)
    write(out/'privacy_budget.json',{'spent':acc.spent_budget,'total':list(acc.total()),'ceiling':[10.5,0],
          'slack':0,'extra_fit_blocked':blocked,'seed_noise':None,'public_norm':float(np.sqrt(DIM)),
          'scope':'Somente cada treinamento DP. Corpus, baseline não privado e escores são sintéticos públicos; o pacote inteiro não é uma publicação DP de dados confidenciais.'})
    seal(out); return verify(out)


def verify(directory):
    out=Path(directory);integrity(out);d=read(out/'data.json');assert d==data()
    x=np.asarray(d['x']);check_domain(x);rs=read(out/'results.json')
    assert len(rs)==4 and [r['epsilon'] for r in rs]==[None,.5,2.,8.]
    for r in rs:
        model=read(out/(r['id']+'_model.json'))
        scores=expit(x@model['coef']+model['intercept'])
        assert np.allclose(scores,r['scores'],rtol=1e-10,atol=1e-12)
        recomputed=summarize(np.asarray(r['scores']),d)
        assert all(r[k]==v for k,v in recomputed.items())
        assert not any('privacy' in w.lower() or 'converg' in w.lower() for w in r['warnings'])
    b=read(out/'privacy_budget.json')
    assert b['spent']==[[.5,0],[2.,0],[8.,0]] and b['total']==[10.5,0] and b['extra_fit_blocked']
    assert [r['accountant'] for r in rs]==[[0,0],[.5,0],[2.5,0],[10.5,0]]
    return {'lab':'L25','verified':True,'fits':4,'privacy_fits':3,'attack_evaluation_per_model':160,
            'utility_per_model':240,'epsilon_composed':10.5,'delta':0}
