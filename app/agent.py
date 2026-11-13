from __future__ import annotations
import datetime as dt,json,time,uuid
from dataclasses import dataclass,field
from .models import PendingAction
from .tools import SPECS,WRITE,execute,validate
SYSTEM="你是个人任务管理 Agent。数量、完成率和逾期必须查询真实数据库；更新任务前必须确定唯一任务。创建和更新任务必须等待用户确认。"
@dataclass
class Step:kind:str;content:str;tool:str|None=None;args:dict|None=None;ms:int=0
@dataclass
class Result:
 answer:str;steps:list[Step]=field(default_factory=list);tool_calls:int=0;total_ms:int=0;stopped_by:str="answer";pending:list[PendingAction]=field(default_factory=list)
 @property
 def pending_writes(self):return self.pending
async def run_agent(llm,db,uid,q,s,max_steps=None):
 msgs=[{"role":"system","content":SYSTEM},{"role":"user","content":q}];steps=[];pending=[];start=time.perf_counter();calls=0;limit=max(1,min(max_steps or s.agent_max_steps,s.agent_max_steps))
 for _ in range(limit):
  msg,_=await llm.with_tools(msgs,SPECS,temperature=.2);tcs=getattr(msg,"tool_calls",None) or []
  if not tcs:return Result(msg.content or "",steps+[Step("answer",msg.content or "")],calls,int((time.perf_counter()-start)*1000),"answer",pending)
  msgs.append({"role":"assistant","content":msg.content,"tool_calls":[{"id":c.id,"type":"function","function":{"name":c.function.name,"arguments":c.function.arguments}} for c in tcs]})
  for c in tcs:
   calls+=1;n=c.function.name
   try:a=json.loads(c.function.arguments or "{}")
   except:a={}
   if n in WRITE and s.agent_confirm_write:
    e=validate(n,a);r={"error":e} if e else None
    if not e:
     x=PendingAction(id=uuid.uuid4().hex,owner_id=uid,tool=n,args_json=json.dumps(a,ensure_ascii=False),expires_at=dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)+dt.timedelta(minutes=s.agent_confirm_ttl_minutes));db.add(x);db.commit();pending.append(x);r={"action_id":x.id,"status":"pending_confirmation"}
   else:r=execute(n,a,db,uid)
   steps.append(Step("tool_result",json.dumps(r,ensure_ascii=False),n));msgs.append({"role":"tool","tool_call_id":c.id,"content":json.dumps(r,ensure_ascii=False)})
 return Result("达到最大步数",steps,calls,int((time.perf_counter()-start)*1000),"max_steps",pending)
