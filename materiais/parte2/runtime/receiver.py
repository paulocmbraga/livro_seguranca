from http.server import HTTPServer, BaseHTTPRequestHandler
import json


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        print(json.dumps({'path': self.path, 'received': True}), flush=True)
        self.send_response(200); self.end_headers(); self.wfile.write(b'RECEBIDO')


HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
