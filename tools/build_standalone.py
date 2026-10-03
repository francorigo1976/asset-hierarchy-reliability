"""Build dist/AssetHierarchy.html: one self-contained file (UI + Python app via Pyodide) that runs in a browser."""
import base64, io, subprocess, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.27.2/full/"

SHIM = r"""
<style>#boot{position:fixed;inset:0;background:var(--bg);color:var(--fg);display:flex;flex-direction:column;
align-items:center;justify-content:center;gap:10px;z-index:9;font:15px system-ui}</style>
<div id="boot"><b>Asset Hierarchy</b><span id="bootmsg">Loading Python engine (first load takes ~20 s)…</span></div>
<script>
(function(){
const BASE=window.PYODIDE_BASE||"__PYODIDE__", APP="__APPZIP__", KEY="asset-hierarchy-state-v1";
const b64=s=>Uint8Array.from(atob(s),c=>c.charCodeAt(0));
const toB64=u=>{let s="";for(let i=0;i<u.length;i+=0x8000)s+=String.fromCharCode.apply(null,u.subarray(i,i+0x8000));return btoa(s)};
let py,bridge;
const ready=(async()=>{
  await new Promise((ok,bad)=>{const s=document.createElement("script");s.src=BASE+"pyodide.js";s.onload=ok;
    s.onerror=()=>bad(new Error("Could not load the Python engine from "+BASE+" — check your internet connection."));document.head.appendChild(s)});
  py=await loadPyodide({indexURL:BASE});
  py.unpackArchive(b64(APP).buffer,"zip",{extractDir:"/pylib"});
  py.runPython("import sys; sys.path.insert(0,'/pylib')");
  bridge=py.pyimport("asset_hierarchy.webbridge");
  let st=null;try{st=JSON.parse(localStorage.getItem(KEY)||"null")}catch(e){}
  bridge.start(st&&st.db?st.db:"", st?st.audit||"":"");
  document.getElementById("boot").remove();
})().catch(e=>{document.getElementById("bootmsg").textContent="Failed to start: "+e.message});
function save(){try{const r=bridge.snapshot().toJs();localStorage.setItem(KEY,JSON.stringify({db:r[0],audit:r[1]}))}
  catch(e){console.warn("could not save state",e)}}
const realFetch=window.fetch.bind(window);
window.fetch=async function(url,opt={}){
  if(!String(url).startsWith("/api"))return realFetch(url,opt);
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


def build() -> Path:
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
    html = (ROOT / "asset_hierarchy/web/index.html").read_text(encoding="utf-8")
    shim = SHIM.replace("__PYODIDE__", PYODIDE).replace("__APPZIP__", base64.b64encode(buf.getvalue()).decode())
    out = ROOT / "dist" / "AssetHierarchy.html"
    out.write_text(html.replace("<body>", "<body>" + shim, 1), encoding="utf-8")
    return out


if __name__ == "__main__":
    p = build()
    print(p, round(p.stat().st_size / 1024), "KB")
