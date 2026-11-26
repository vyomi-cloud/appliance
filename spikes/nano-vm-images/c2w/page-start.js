// SPIKE: container2wasm WASI image in a Worker, no networking (net=none). Adapted from ktock/container2wasm-demo (Apache-2.0).
var worker;
function startWasi(elemId, workerFileName, workerImageNamePrefix, workerImageChunks) {
    const xterm = new Terminal();
    window.__term = xterm;
    xterm.open(document.getElementById(elemId));
    const { master, slave } = openpty();
    var termios = slave.ioctl("TCGETS");
    termios.iflag &= ~(ISTRIP | INLCR | IGNCR | ICRNL | IXON);
    termios.oflag &= ~(OPOST);
    termios.lflag &= ~(ECHO | ECHONL | ICANON | ISIG | IEXTEN);
    slave.ioctl("TCSETS", new Termios(termios.iflag, termios.oflag, termios.cflag, termios.lflag, termios.cc));
    xterm.loadAddon(master);
    worker = new Worker(workerFileName);
    worker.postMessage({type: "init", imagename: workerImageNamePrefix, chunks: workerImageChunks});
    new TtyServer(slave).start(worker, undefined);
}

function getNetParam() {
    var vars = location.search.substring(1).split('&');
    for (var i = 0; i < vars.length; i++) {
        var kv = vars[i].split('=');
        if (decodeURIComponent(kv[0]) == 'net') {
            return {
                mode: kv[1],
                param: kv[2],
            };
        }
    }
    return null;
}
