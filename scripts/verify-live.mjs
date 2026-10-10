import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
const result=spawnSync('python3',['skills/socialquery-data/scripts/socialquery_api.py','discover','--platform','hackernews'],{encoding:'utf8',env:{...process.env,SOCIALQUERY_API_KEY:''}});
assert.equal(result.status,0,result.stderr);
assert.ok(JSON.parse(result.stdout).some(endpoint=>endpoint.id==='get_hackernews_search'));
console.log('Skill helper discovers live endpoints without an API key. No data credits spent.');
