import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import path from 'node:path';
import os from 'node:os';
let pending;
export function loadUpstream(){return pending??=load();}
async function load(){
 // No caller-controlled upstream environment, auth modes, hooks, file cache, or logging.
 for(const k of Object.keys(process.env))if(k.startsWith('MS365_MCP_'))delete process.env[k];
 process.env.MS365_MCP_LOG_DIR=path.join(os.tmpdir(),'m365-disabled-logs');
 process.env.MS365_MCP_AUDIT_LOG='false';
 process.env.MS365_MCP_GRAPH_MAX_RETRIES='0';process.env.MS365_MCP_GRAPH_TIMEOUT_MS='10000';
 const require=createRequire(import.meta.url);
 const root=path.dirname(require.resolve('@softeria/ms-365-mcp-server'));
 const imp=file=>import(pathToFileURL(path.join(root,file)));
 const {default:logger}=await imp('logger.js');logger.silent=true;logger.clear();
 const [{default:Server},{default:Auth},{unwrapCache}]=await Promise.all([imp('server.js'),imp('auth.js'),imp('token-cache-storage.js')]);
 return {Server,Auth,unwrap:unwrapCache};
}
