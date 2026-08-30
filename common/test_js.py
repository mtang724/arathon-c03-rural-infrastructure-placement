"""
Run a generated page's JavaScript under QuickJS against a DOM shim.

    python -m common.test_js planner.html

A page in this repository is a build artifact with several megabytes of injected
data, and the failure mode that matters is not a wrong number -- it is an
exception partway through initialisation that leaves the lower half of the page
blank while the top half looks fine. That is exactly how the blank-sections bug
in the analysis report was found, and it is invisible to any check that only
looks at the file.

This executes the page's script with a minimal `document`, canvas context and
event model, reports the first exception with the line that raised it, and
lists every element id the script asked for that the markup does not define.

WHAT IT DOES NOT DO. It does not render, so it cannot tell you the map is
upside down. It catches crashes and missing ids. Treat a pass as "the page will
load", not as "the page is correct".
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys

SHIM = r"""
var __log=[];
function __El(id){ this.id=id; this.children=[]; this._html=""; this.className="";
  this.style={}; this.textContent=""; this.dataset={}; this.value=0;
  this.clientWidth=900; this.clientHeight=480; this.offsetWidth=40;
  this.min=0; this.max=100; this.step=1;
  this.classList={add:function(){},remove:function(){},toggle:function(){},
                  contains:function(){return false;}}; }
Object.defineProperty(__El.prototype,"innerHTML",{
  get:function(){ return this._html||""; },
  set:function(v){ this._html=String(v);
    var re=/id="([A-Za-z0-9_\-]+)"/g, m;
    while((m=re.exec(this._html))!==null){ if(!__store[m[1]]) __store[m[1]]=new __El(m[1]); }
  }});
__El.prototype.appendChild=function(c){ this.children.push(c); return c; };
__El.prototype.setAttribute=function(k,v){ this[k]=v; };
__El.prototype.getAttribute=function(k){ return this[k]===undefined?null:this[k]; };
__El.prototype.addEventListener=function(){};
__El.prototype.removeEventListener=function(){};
__El.prototype.getBoundingClientRect=function(){ return {left:0,top:0,width:900,height:480}; };
__El.prototype.querySelectorAll=function(){ return []; };
__El.prototype.querySelector=function(){ return null; };
__El.prototype.getContext=function(){ return new __Ctx(); };
__El.prototype.closest=function(){ return null; };
Object.defineProperty(__El.prototype,"parentNode",{get:function(){ return __store.__stage; }});
function __Ctx(){}
["setTransform","clearRect","fillRect","beginPath","arc","fill","stroke","moveTo",
 "lineTo","closePath","fillText","strokeRect","setLineDash","putImageData","drawImage",
 "save","restore","translate","scale","rect","clip"].forEach(function(k){
  __Ctx.prototype[k]=function(){}; });
__Ctx.prototype.createImageData=function(w,h){
  return {width:w,height:h,data:new Array(w*h*4).fill(0)}; };
__Ctx.prototype.measureText=function(){ return {width:10}; };

var __IDS = __IDLIST__;
var __store={};
__IDS.forEach(function(i){ __store[i]=new __El(i); });
__store.__stage=new __El("__stage");

var document={
  getElementById:function(id){ if(!__store[id]){ __log.push("MISSING #"+id); return null; }
    return __store[id]; },
  createElement:function(t){ var e=new __El("<"+t+">"); e.tag=t; return e; },
  createElementNS:function(ns,t){ var e=new __El("<"+t+">"); e.tag=t; return e; },
  querySelectorAll:function(){ return []; },
  querySelector:function(){ return null; },
  addEventListener:function(){},
  documentElement:new __El("root")
};
function getComputedStyle(){ return { getPropertyValue:function(){ return "#4da3ff"; } }; }
function matchMedia(){ return { matches:false, addEventListener:function(){},
  addListener:function(){} }; }
function addEventListener(){}
function setTimeout(f){ f(); return 0; }   /* synchronous: the progressive
   coverage-surface build is a setTimeout chain, and a no-op stub would let the
   test pass without ever running the optimiser it is meant to exercise. */
function atob(s){
  var T="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  var o="",i=0; s=String(s).replace(/[^A-Za-z0-9+/]/g,"");
  while(i<s.length){
    var e1=T.indexOf(s.charAt(i++)),e2=T.indexOf(s.charAt(i++));
    var e3=T.indexOf(s.charAt(i++)),e4=T.indexOf(s.charAt(i++));
    o+=String.fromCharCode((e1<<2)|(e2>>4));
    if(e3>=0)o+=String.fromCharCode(((e2&15)<<4)|(e3>>2));
    if(e4>=0)o+=String.fromCharCode(((e3&3)<<6)|e4);
  }
  return o;
}
var devicePixelRatio=1;
var location={reload:function(){}};
var window=this;
"""


def run(path, verbose=True, call=None):
    html = io.open(path, encoding="utf-8").read()
    if "<script>" not in html:
        raise SystemExit(f"{path} has no <script> block")
    js = html.split("<script>")[1].split("</script>")[0]
    ids = sorted(set(re.findall(r'id="([a-zA-Z0-9\-_]+)"', html)))

    import quickjs
    ctx = quickjs.Context()
    ctx.set_memory_limit(1 << 31)
    ctx.set_max_stack_size(1 << 22)
    ok = True
    try:
        ctx.eval(SHIM.replace("__IDLIST__", json.dumps(ids)))
    except Exception as e:
        print(f"FAILED in the shim itself: {str(e)[:400]}")
        return False
    try:
        ctx.eval(js)
        if verbose:
            print(f"  ok    {path} script evaluated ({len(js)/1e6:.2f} MB, "
                  f"{len(ids)} ids)")
    except Exception as e:
        ok = False
        print(f"  FAIL  {path}\n        -> {str(e)[:900]}")

    if ok and call:
        try:
            print(f"  -> {ctx.eval(call)}")
        except Exception as e:
            ok = False
            print(f"  FAIL  evaluating {call!r}\n        -> {str(e)[:900]}")

    log = json.loads(ctx.eval("JSON.stringify(__log.slice(0,40))"))
    missing = sorted({x for x in log if x.startswith("MISSING")})
    if missing:
        ok = False
        print("\n  element ids the script wanted and the markup does not define:")
        for m in missing:
            print("   ", m)
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--call", default=None,
                    help="a JS expression to evaluate after load, e.g. a solve")
    a = ap.parse_args()
    good = all(run(p, call=a.call) for p in a.pages)
    sys.exit(0 if good else 1)


if __name__ == "__main__":
    main()
