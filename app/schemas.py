import datetime as dt
from pydantic import BaseModel,ConfigDict,Field
class RegisterIn(BaseModel):email:str;name:str;password:str=Field(min_length=8,max_length=72)
class LoginIn(BaseModel):email:str;password:str
class UserOut(BaseModel):model_config=ConfigDict(from_attributes=True);id:int;email:str;name:str;created_at:dt.datetime
class AgentRequest(BaseModel):question:str=Field(min_length=2,max_length=20000);max_steps:int|None=Field(None,ge=1,le=10)
class PendingOut(BaseModel):id:str;tool:str;args:dict;expires_at:dt.datetime
class AgentResponse(BaseModel):ok:bool;answer:str;steps:list[dict];tool_calls:int;total_ms:int;stopped_by:str;pending_writes:list[PendingOut]=[]
class ConfirmIn(BaseModel):action_id:str
class ConfirmOut(BaseModel):ok:bool;tool:str;result:dict
ConfirmWriteIn=ConfirmIn;ConfirmWriteOut=ConfirmOut;PendingWriteOut=PendingOut
