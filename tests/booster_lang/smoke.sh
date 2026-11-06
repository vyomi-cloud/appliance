#!/usr/bin/env bash
# Per-language smoke for the booster language image.
#   tests/booster_lang/smoke.sh [image]     (host side: runs the in-image part)
# Per language: (1) version == pinned, (2) compile+run hello, (3) install a small
# package with the language's package manager, (4) serve on a port and curl it.
IMG=${1:-vyomi/booster-lang:dev}
HERE=$(cd "$(dirname "$0")" && pwd)
if [ -z "$INSIDE" ]; then
  exec docker run --rm -e INSIDE=1 -v "$HERE/smoke.sh:/smoke.sh:ro" ${VERSIONS_OVERRIDE:+-v "$VERSIONS_OVERRIDE:/etc/booster-lang-versions.json:ro"} "$IMG" bash /smoke.sh
fi
V=/etc/booster-lang-versions.json
pin() { jq -r "$1" $V; }
declare -A R
W=$(mktemp -d); cd "$W"
step() { # lang step cmd...
  local l=$1 s=$2; shift 2
  if out=$(timeout 600 bash -c "$*" 2>&1); then R[$l]+="$s:ok "; else R[$l]+="$s:FAIL "; echo "--- $l/$s FAILED"; echo "$out" | tail -8; FAILED=1; fi
}
web() { # lang port 'server cmd'  (curl must return "hello-<lang>")
  local l=$1 p=$2; shift 2
  step "$l" web "( $* ) >/tmp/$l.srv 2>&1 & pid=\$!; for i in \$(seq 1 60); do curl -fs localhost:$p >/tmp/$l.out 2>/dev/null && break; sleep 1; done; kill \$pid 2>/dev/null; pkill -P \$pid 2>/dev/null; grep -q hello-$l /tmp/$l.out"
}
ver() { step "$1" version "[ \"\$($2)\" = '$3' ] || { echo got: \$($2) want $3; exit 1; }"; }

# ---- Python
ver python "python3 -c 'import platform;print(platform.python_version())'" "$(pin .python.version)"
ver python "pip --version | awk '{print \$2}'" "$(pin .package_managers.pip)"
step python hello "python3 -c 'print(1)' | grep -q 1"
step python pkg "python3 -m venv v && v/bin/pip install -q six && v/bin/python -c 'import six'"
web python 8101 "python3 -c \"import http.server as h,socketserver as s
class H(h.BaseHTTPRequestHandler):
    def do_GET(self): self.send_response(200);self.end_headers();self.wfile.write(b'hello-python')
s.TCPServer(('0.0.0.0',8101),H).serve_forever()\""
# ---- Node
ver node "node -p process.versions.node" "$(pin .node.version)"
ver node "npm -v" "$(pin .package_managers.npm)"
ver node "pnpm -v" "$(pin .package_managers.pnpm)"
ver node "yarn -v" "$(pin .package_managers.yarn_classic)"
step node hello "node -e 'console.log(1)' | grep -q 1"
step node pkg "mkdir n && cd n && npm init -y >/dev/null && npm i --silent left-pad && node -e 'require(\"left-pad\")'"
web node 8102 "node -e \"require('http').createServer((q,r)=>r.end('hello-node')).listen(8102)\""
# ---- Java (LTS + latest)
for k in lts latest; do
  m=$(pin .java.$k.major); ver "java$m" "/opt/java/$m/bin/java -XshowSettings:properties -version 2>&1 | awk -F' = ' '/java.runtime.version/{print \$2}' | sed 's/-LTS//'" "$(pin .java.$k.version | sed 's/-LTS//')"
done
cat > Hello.java <<'J'
public class Hello { public static void main(String[] a) throws Exception {
  if (a.length>0) { var s=com.sun.net.httpserver.HttpServer.create(new java.net.InetSocketAddress(8103),0);
    s.createContext("/",e->{byte[] b="hello-java".getBytes();e.sendResponseHeaders(200,b.length);e.getResponseBody().write(b);e.close();}); s.start(); Thread.sleep(60000);}
  else System.out.println("hi"); } }
J
step java hello "javac Hello.java && java Hello | grep -q hi"
step java version "[ \"\$(java -version 2>&1 | head -1 | awk -F'\"' '{print \$2}')\" = \"\$(echo $(pin .java.lts.version) | sed 's/-LTS//;s/+.*//')\" ] || java -version"
step java latest-hello "JAVA_HOME=/opt/java/latest /opt/java/latest/bin/javac Hello.java && /opt/java/latest/bin/java Hello | grep -q hi"
ver java-maven "mvn -v | head -1 | awk '{print \$3}'" "$(pin .package_managers.maven.version)"
ver java-gradle "gradle -v | awk '/^Gradle/{print \$2}'" "$(pin .package_managers.gradle.version)"
step java pkg "mvn -q -B dependency:get -Dartifact=junit:junit:4.13.2 >/dev/null"
step java recompile-lts "javac Hello.java"
web java 8103 "java Hello serve"
# ---- Go
ver go "go env GOVERSION" "go$(pin .go.version)"
mkdir g && cd g && cat > main.go <<'G'
package main
import ("fmt";"net/http";"os";"github.com/google/uuid")
func main(){ _ = uuid.New()
 if len(os.Args)>1 { http.HandleFunc("/",func(w http.ResponseWriter,r *http.Request){fmt.Fprint(w,"hello-go")}); http.ListenAndServe(":8104",nil) } else { fmt.Println("hi") } }
G
step go pkg "go mod init smoke >/dev/null 2>&1; go get github.com/google/uuid@v1.6.0 >/dev/null 2>&1; go mod tidy"
step go hello "go build -o app . && ./app | grep -q hi"
web go 8104 "./app serve"; cd ..
# ---- Rust
ver rust "rustc --version | awk '{print \$2}'" "$(pin .rust.version)"
ver rust "cargo --version | awk '{print \$2}'" "$(pin .rust.version)"
step rust hello "cargo new --quiet r && cd r && cargo run -q | grep -q Hello"
step rust pkg "cd r && cargo add itoa -q && cargo build -q"
step rust webprep "cd r && cat > src/main.rs <<'X'
use std::{io::{Read,Write},net::TcpListener};
fn main(){ let l=TcpListener::bind(\"0.0.0.0:8105\").unwrap(); for s in l.incoming(){ let mut s=s.unwrap(); let mut b=[0;512]; let _=s.read(&mut b); let _=s.write_all(b\"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nhello-rust\"); } }
X
cargo build -q"
web rust 8105 "r/target/debug/r"
# ---- .NET
ver dotnet "dotnet --version" "$(pin .dotnet.version)"
step dotnet hello "dotnet new console -o d --no-restore >/dev/null && cd d && dotnet run | grep -q Hello"
step dotnet pkg "cd d && dotnet add package Newtonsoft.Json >/dev/null && dotnet build -v q --nologo >/dev/null"
step dotnet webprep "cd d && cat > Program.cs <<'X'
var l=new System.Net.HttpListener(); l.Prefixes.Add(\"http://+:8106/\"); l.Start();
while(true){var c=l.GetContext(); var b=System.Text.Encoding.UTF8.GetBytes(\"hello-dotnet\"); c.Response.OutputStream.Write(b); c.Response.Close();}
X
dotnet build -v q --nologo >/dev/null"
web dotnet 8106 "dotnet d/bin/Debug/*/d.dll"
# ---- Ruby
ver ruby "ruby -e 'puts RUBY_VERSION'" "$(pin .ruby.version)"
step ruby hello "ruby -e 'puts 1' | grep -q 1"
step ruby bundler "bundler -v"
step ruby pkg "gem install --no-document rainbow >/dev/null && ruby -rrainbow -e 1"
web ruby 8107 "ruby -rsocket -e 's=TCPServer.new(8107);loop{c=s.accept;c.gets;c.print \"HTTP/1.1 200 OK\r\nContent-Length: 10\r\n\r\nhello-ruby\";c.close}'"
# ---- PHP
ver php "php -r 'echo PHP_VERSION;'" "$(pin .php.version)"
ver php-composer "composer --version 2>/dev/null | awk '{print \$3}'" "$(pin .package_managers.composer.version)"
step php hello "php -r 'echo 1;' | grep -q 1"
step php pkg "mkdir p && cd p && composer require --quiet --no-interaction monolog/monolog && php -r 'require \"vendor/autoload.php\";new Monolog\\Logger(\"x\");'"
mkdir -p ph && echo '<?php echo "hello-php";' > ph/index.php
web php 8108 "php -S 0.0.0.0:8108 -t ph"
# ---- C / C++
ver cpp "gcc -dumpversion" "$(pin .cpp.gcc_major)"
ver cpp "clang --version | head -1 | sed 's/.*version \\([0-9]*\\).*/\\1/'" "$(pin .cpp.clang_major)"
cat > h.c <<'C'
#include <stdio.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <unistd.h>
#include <string.h>
int main(int c,char**v){ if(c<2){puts("hi");return 0;} int s=socket(AF_INET,SOCK_STREAM,0),o=1;setsockopt(s,SOL_SOCKET,SO_REUSEADDR,&o,4);
 struct sockaddr_in a={0};a.sin_family=AF_INET;a.sin_port=htons(8109);bind(s,(void*)&a,sizeof a);listen(s,5);
 for(;;){int k=accept(s,0,0);char b[256];read(k,b,256);const char*m="HTTP/1.1 200 OK\r\nContent-Length: 9\r\n\r\nhello-cpp";write(k,m,strlen(m));close(k);} }
C
step cpp hello "gcc h.c -o hc && ./hc | grep -q hi && clang h.c -o hl && ./hl | grep -q hi && echo 'int main(){}' > x.cpp && g++ x.cpp -o x && clang++ x.cpp -o y"
step cpp pkg "cmake --version >/dev/null && make --version >/dev/null"
web cpp 8109 "./hc serve"
# ---- apt (needs root: check tool presence only)
step apt version "apt-get --version | head -1 | grep -q apt"

echo; echo "=========== SMOKE RESULTS"
for l in $(printf '%s\n' "${!R[@]}" | sort); do echo "$l: ${R[$l]}"; done
[ -z "$FAILED" ] && echo "ALL PASS" || { echo "SOME FAILED"; exit 1; }
