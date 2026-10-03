"""Build dist/AssetHierarchy.html (loads the Python engine from a CDN) and dist/AssetHierarchy-offline.html
(engine bundled inside, works with no internet). Both run the full app in a browser via Pyodide."""
import base64, gzip, io, json, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYODIDE_VERSION = "0.27.2"
CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"
ENGINE_FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "python_stdlib.zip", "pyodide-lock.json"]

SHIM = r"""
<style>#boot{position:fixed;inset:0;background:var(--bg);color:var(--fg);display:flex;flex-direction:column;
align-items:center;justify-content:center;gap:10px;z-index:9;font:15px system-ui;text-align:center;padding:20px}</style>
<div id="boot"><b>Asset Hierarchy</b><span id="bootmsg">Loading Python engine (first load takes ~20 s)…</span></div>
__OFFLINE_DATA__
<script>
(function(){
const BASE=window.PYODIDE_BASE||"__CDN__", APP="__APPZIP__", KEY="asset-hierarchy-state-v1", VBASE="https://pyodide.local/";
const OFFLINE=window.__OFFLINE__||null;   // {name: base64(gzip)} when the engine is bundled in this file
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const gunzip=async b=>new Uint8Array(await new Response(new Blob([b]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer());
const files={};let py,bridge;
const realFetch=window.fetch.bind(window);
function save(){try{const r=bridge.snapshot().toJs();localStorage.setItem(KEY,JSON.stringify({db:r[0],audit:r[1]}))}
  catch(e){console.warn("could not save state",e)}}
async function boot(){
  let base=BASE;
  if(OFFLINE){
    document.getElementById("bootmsg").textContent="Unpacking Python engine…";
    for(const k in OFFLINE)files[k]=await gunzip(b64(OFFLINE[k]));
    const dec=new TextDecoder();
    (0,eval)(dec.decode(files["pyodide.asm.js"]));   // defines _createPyodideModule, so pyodide.js will not fetch it
    (0,eval)(dec.decode(files["pyodide.js"]));
    base=VBASE;
  }else{
    await new Promise((ok,bad)=>{const s=document.createElement("script");s.src=BASE+"pyodide.js";s.onload=ok;
      s.onerror=()=>bad(new Error("Could not load the Python engine from "+BASE+" — check your internet connection, or use the offline version of this file."));document.head.appendChild(s)});
  }
  py=await loadPyodide({indexURL:base});
  py.unpackArchive(b64(APP).buffer,"zip",{extractDir:"/pylib"});
  py.runPython("import sys; sys.path.insert(0,'/pylib')");
  bridge=py.pyimport("asset_hierarchy.webbridge");
  let st=null;try{st=JSON.parse(localStorage.getItem(KEY)||"null")}catch(e){}
  bridge.start(st&&st.db?st.db:"", st?st.audit||"":"");
  document.getElementById("boot").remove();
}
const ready=boot().catch(e=>{console.error(e);document.getElementById("bootmsg").textContent="Failed to start: "+(e&&e.message||e)});
window.fetch=async function(url,opt={}){
  if(url instanceof URL)url=url.href;   // some hosts/sandboxes cannot clone URL objects (DataCloneError)
  if(typeof url==="string"&&url.startsWith(VBASE)&&OFFLINE){
    const n=url.slice(VBASE.length).split("?")[0];
    if(files[n])return new Response(files[n],{status:200,headers:{"Content-Type":n.endsWith(".wasm")?"application/wasm":n.endsWith(".json")?"application/json":"application/octet-stream"}});
  }
  if(typeof url!=="string"||!url.startsWith("/api"))return realFetch(url,opt);
  await ready;
  const u=new URL(url,"http://x"),q={};u.searchParams.forEach((v,k)=>q[k]=v);
  const method=(opt.method||"GET").toUpperCase();let body="null",fname="",content=null;
  if(opt.body instanceof FormData){const f=opt.body.get("file");fname=f.name;content=new Uint8Array(await f.arrayBuffer())}
  else if(opt.body)body=opt.body;
  const r=bridge.handle(method,u.pathname,JSON.stringify(q),body,fname,content?py.toPy(content):null).toJs();
  const [status,payload,file,name]=r;
  if(method!=="GET"||file)save();
  if(file)return new Response(new Blob([file],{type:"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}),{status,headers:{"Content-Disposition":'attachment; filename="'+name+'"'}});
  return new Response(payload,{status,statusText:status==200?"OK":"Error",headers:{"Content-Type":"application/json"}});
};
})();
</script>
"""


def app_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for pkg in ("asset_hierarchy", "data_export"):
            for p in (ROOT / pkg).rglob("*.py"):
                if "web" in p.relative_to(ROOT).parts[1:2]:
                    continue
                z.write(p, p.relative_to(ROOT).as_posix())
        with tempfile.TemporaryDirectory() as td:   # pure-python deps, installed from PyPI wheels
            subprocess.check_call([sys.executable, "-m", "pip", "download", "-q", "--no-deps", "-d", td,
                                   "--only-binary=:all:", "--platform", "any", "openpyxl", "et_xmlfile"])
            for w in Path(td).glob("*.whl"):
                with zipfile.ZipFile(w) as wz:
                    for n in wz.namelist():
                        if not n.endswith("/"):
                            z.writestr(n, wz.read(n))
    return buf.getvalue()


def engine_files() -> dict:
    with tempfile.TemporaryDirectory() as td:
        subprocess.check_call(["npm", "pack", "-s", f"pyodide@{PYODIDE_VERSION}"], cwd=td)
        import tarfile
        tgz = next(Path(td).glob("pyodide-*.tgz"))
        with tarfile.open(tgz) as t:
            return {n: gzip.compress(t.extractfile(f"package/{n}").read(), 9) for n in ENGINE_FILES}


def build(offline: bool) -> Path:
    html = (ROOT / "asset_hierarchy/web/index.html").read_text(encoding="utf-8")
    data = ""
    if offline:
        enc = {k: base64.b64encode(v).decode() for k, v in engine_files().items()}
        data = "<script>window.__OFFLINE__=" + json.dumps(enc) + ";</script>"
    shim = (SHIM.replace("__CDN__", CDN).replace("__APPZIP__", base64.b64encode(app_zip()).decode())
            .replace("__OFFLINE_DATA__", data))
    out = ROOT / "dist" / ("AssetHierarchy-offline.html" if offline else "AssetHierarchy.html")
    out.write_text(html.replace("<body>", "<body>" + shim, 1), encoding="utf-8")
    return out


if __name__ == "__main__":
    for off in (False, True):
        p = build(off)
        print(p.name, round(p.stat().st_size / 1024), "KB")
