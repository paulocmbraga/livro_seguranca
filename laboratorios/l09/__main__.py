import argparse
import json
from .campaign import run, verify
from .llm import OllamaAdapter


def main():
    parser = argparse.ArgumentParser(description="L09: bancada local de RAG adversarial")
    parser.add_argument("command", choices=("run", "verify"))
    parser.add_argument("--out", required=True, help="Diretório novo para run; existente para verify")
    parser.add_argument("--split", choices=("dev", "eval", "all"), default="eval")
    parser.add_argument("--model", help="Nome exato de modelo já instalado no Ollama local")
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.command == "verify":
        result = verify(args.out)
    else:
        adapter = OllamaAdapter(args.model, args.max_calls) if args.model else None
        report = run(args.out, args.split, adapter, args.repeats)
        result = {k: report[k] for k in ("adapter", "cases", "trajectories", "summary")}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if any(s["errors"] for s in result["summary"].values()):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
