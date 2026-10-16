import manifest from './tools-manifest.json' with {type:'json'};
export {manifest};
export const messageFields='id,subject,from,toRecipients,receivedDateTime,isRead,bodyPreview';
export const folderFields='id,displayName,parentFolderId,childFolderCount,totalItemCount,unreadItemCount';
export function prepare(name,args={}) {
 const schema=manifest.find(t=>t.name===name)?.inputSchema;
 if(!schema || !args || typeof args!=='object' || Array.isArray(args))throw Error('Invalid arguments');
 for(const k of schema.required)if(!Object.hasOwn(args,k))throw Error('Missing argument');
 for(const [k,v] of Object.entries(args)){
  if(!Object.hasOwn(schema.properties,k))throw Error('Unknown argument');
  const s=schema.properties[k];
  if(s.type==='integer') {if(!Number.isInteger(v)||v<s.minimum||v>s.maximum)throw Error('Invalid bound');}
  else if(typeof v!=='string'||(s.minLength && v.length<s.minLength)||(s.maxLength && v.length>s.maxLength)||(s.pattern&&!new RegExp(s.pattern).test(v))||(s.enum&&!s.enum.includes(v)))throw Error('Invalid argument');
 }
 if(args.search && (args.skip!==undefined||args.orderby!==undefined))throw Error('Search cannot combine with skip/order');
 const message=name.includes('message');
 return {...args,...(name==='get-mail-message'?{}:{top:args.top??10}),...(args.search?{search:`"${args.search}"`}:{}),fetchAllPages:false,select:message?messageFields+(name==='get-mail-message'?',body':''):folderFields};
}
export function allowedGraphURL(value,method='GET') {
 const u=new URL(value);
 if(method!=='GET'||u.origin!=='https://graph.microsoft.com'||u.username||u.password||u.hash||!/^\/v1\.0\/me\/(messages(?:\/[A-Za-z0-9_=-]{1,512})?|mailFolders(?:\/[A-Za-z0-9_=-]{1,512}\/(?:messages|childFolders))?)$/.test(u.pathname))throw Error('Graph boundary');
 const allowed=new Set(['$top','$skip','$select','$search','$orderby']);
 for(const [k,v] of u.searchParams)if(!allowed.has(k)||u.searchParams.getAll(k).length!==1||v.length>512)throw Error('Graph query boundary');
 return u;
}
