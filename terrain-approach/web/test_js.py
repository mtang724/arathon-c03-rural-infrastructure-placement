"""Execute the report's JavaScript against a minimal DOM shim to find the
runtime error that is blanking the later sections."""
import io, json, re, sys
import quickjs

html = io.open("eda_report.html", encoding="utf-8").read()
js = html.split("<script>")[1].split("</script>")[0]

# every id the script may look up
ids = sorted(set(re.findall(r'id="([a-zA-Z0-9\-]+)"', html)))

SHIM = """
var __log=[];
function __El(id){ this.id=id; this.children=[]; this._html=""; this.className="";
  this.style={}; this.textContent=""; this.dataset={}; this.clientWidth=900; this.clientHeight=480;
  this.offsetWidth=40; }
Object.defineProperty(__El.prototype,"innerHTML",{
  get:function(){ return this._html||""; },
  set:function(v){ this._html=String(v);
    var re=/id="([A-Za-z0-9_\-]+)"/g, m;
    while((m=re.exec(this._html))!==null){ if(!__store[m[1]]) __store[m[1]]=new __El(m[1]); }
  }});
__El.prototype.appendChild=function(c){ this.children.push(c); return c; };
__El.prototype.setAttribute=function(k,v){ if(v===undefined||v===null)
   __log.push("WARN setAttribute("+k+", "+v+") on <"+(this.tag||this.id)+">"); this[k]=v; };
__El.prototype.getAttribute=function(k){ return this[k]; };
__El.prototype.addEventListener=function(){};
__El.prototype.getBoundingClientRect=function(){ return {left:0,top:0,width:900,height:480}; };
__El.prototype.querySelectorAll=function(){ return []; };
__El.prototype.getContext=function(){ return new __Ctx(); };
__El.prototype.closest=function(){ return null; };
function __Ctx(){}
__Ctx.prototype.setTransform=function(){};__Ctx.prototype.clearRect=function(){};
__Ctx.prototype.fillRect=function(){};__Ctx.prototype.beginPath=function(){};
__Ctx.prototype.arc=function(){};__Ctx.prototype.fill=function(){};
__Ctx.prototype.stroke=function(){};__Ctx.prototype.moveTo=function(){};
__Ctx.prototype.lineTo=function(){};__Ctx.prototype.closePath=function(){};
__Ctx.prototype.fillText=function(){};__Ctx.prototype.strokeRect=function(){};
__Ctx.prototype.setLineDash=function(){};
__Ctx.prototype.createImageData=function(w,h){ return {width:w,height:h,data:new Array(w*h*4).fill(0)}; };
__Ctx.prototype.putImageData=function(){};
__Ctx.prototype.drawImage=function(){};
__Ctx.prototype.measureText=function(){ return {width:10}; };


var __IDS = __IDLIST__;
var __store={};
__IDS.forEach(function(i){ __store[i]=new __El(i); });

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
function getComputedStyle(){ return { getPropertyValue:function(k){ return "#0F6E70"; } }; }
function matchMedia(q){ return { matches:false, addEventListener:function(){}, addListener:function(){} }; }
function addEventListener(){}
var devicePixelRatio=1;
var location={reload:function(){}};
var window=this;
"""

shim = SHIM.replace("__IDLIST__", json.dumps(ids))

# split the script into its top-level blocks so we can attribute a failure
blocks = re.split(r'(?m)^/\* -+ (.*?) -+ \*/$', js)
head = blocks[0]
pairs = [(blocks[i], blocks[i + 1]) for i in range(1, len(blocks) - 1, 2)]

ctx = quickjs.Context()
ctx.set_memory_limit(1 << 30)
try:
    ctx.eval(shim)
    ctx.eval(head)          # data + helpers
except Exception as e:
    print("FAILED in shim/head:", str(e)[:600]); sys.exit(1)

print(f"{len(pairs)} script blocks\n")
for name, body in pairs:
    try:
        ctx.eval(body)
        print(f"  ok    {name}")
    except Exception as e:
        msg = str(e).replace("\n", " ")[:400]
        print(f"  FAIL  {name}\n        -> {msg}")

warns = ctx.eval("JSON.stringify(__log.slice(0,25))")
w = json.loads(warns)
if w:
    print("\nwarnings:")
    for x in w[:25]:
        print("  ", x)
