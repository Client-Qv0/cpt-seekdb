"""Local deterministic HTTP fixture for AI SQL integration tests. No real models."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *_):
        pass

    def reply(self, status, data):
        encoded = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if self.path == "/requests":
            self.reply(200, self.requests)
        else:
            self.reply(404, {})

    def do_POST(self):
        try:
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path == "/reset":
                self.requests.clear()
                self.reply(200, {})
                return
            self.requests.append({"path": self.path, "body": data})
            if self.path == "/api/generate":
                if data.get("stream") is not False:
                    self.reply(400, {"error": "stream must be false"})
                else:
                    self.reply(200, {"response": "generated", "done": True})
            elif self.path.startswith("/chat/completions"):
                content = "" if self.path.endswith("empty") else "completed"
                self.reply(200, {"choices": [{"message": {"content": content}}]})
            elif self.path in ("/embeddings", "/api/embed", "/embeddings-invalid"):
                inputs = data["input"]
                inputs = [inputs] if isinstance(inputs, str) else inputs
                dimension = data.get("dimensions", 4)
                if not isinstance(dimension, int) or not 0 < dimension <= 4096:
                    self.reply(400, {"error": "invalid dimension"})
                    return
                vectors = [[sum(text.encode()) % 997 + 1 + i / 1000 for i in range(dimension)]
                           for text in inputs]
                if self.path.endswith("invalid"):
                    vectors[0] = ["not-a-number"]
                if self.path == "/api/embed":
                    self.reply(200, {"embeddings": vectors})
                else:
                    self.reply(200, {"data": [{"index": i, "embedding": vectors[i]}
                                              for i in reversed(range(len(vectors)))]})
            elif self.path == "/v1/rerank":
                results = [{"index": i, "relevance_score": float(text.rsplit("-", 1)[-1]) % 5}
                           for i, text in enumerate(data["documents"])]
                self.reply(200, {"results": list(reversed(results))})
            else:
                self.reply(404, {"error": "unknown fixture endpoint"})
        except (ValueError, KeyError, TypeError) as error:
            self.reply(400, {"error": str(error)})


if __name__ == "__main__":
    ThreadingHTTPServer(("127.0.0.1", 18080), Handler).serve_forever()
