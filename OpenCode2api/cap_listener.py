import http.server, json, sys
class H(http.server.BaseHTTPRequestHandler):
    def _cap(self):
        ln=int(self.headers.get("Content-Length") or 0)
        body=self.rfile.read(ln).decode("utf-8","replace") if ln else ""
        hdrs={k.lower():v for k,v in self.headers.items()}
        with open("cap.log","a",encoding="utf-8") as f:
            f.write(json.dumps({"method":self.command,"path":self.path,"headers":hdrs,"body":body[:400]},ensure_ascii=False)+"\n")
    def do_POST(self):
        self._cap()
        self.send_response(200); self.send_header("Content-Type","text/event-stream"); self.end_headers()
        self.wfile.write(b'data: {"id":"c1","object":"chat.completion.chunk","choices":[{"index":0,"delta":{"content":"ok"}}]}\n\n')
        self.wfile.write(b"data: [DONE]\n\n")
    def do_GET(self):
        self._cap()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers()
        self.wfile.write(b'{"data":[]}')
    def log_message(self,*a): pass
http.server.HTTPServer(("127.0.0.1",8399),H).serve_forever()
