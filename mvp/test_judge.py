"""Real Docker acceptance tests: seeds, errors, time/output limits and isolation."""
import concurrent.futures
import json
import os
from pathlib import Path
import time

import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from judge_gateway.executor import run_judge


def main():
    problems=json.loads((Path(__file__).parent/'seed.json').read_text(encoding='utf-8'))
    start=time.monotonic()
    workers=max(1,min(3,int(os.getenv('JUDGE_TEST_CONCURRENCY','1'))))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        results=list(pool.map(lambda p:run_judge(p['solution'],p['tests']),problems))
    for p,r in zip(problems,results):
        assert r['passed'], (p['id'],r)
        print(f"PASS {p['id']}: {len(r['tests'])} tests")
    tests=[{'input':'','expected':'ok'}]
    cases=[('compile error','int main( {'),('wrong output','int main() {}'),
           ('timeout','int main() { for(;;) {} }'),
           ('output limit','#include <iostream>\nint main(){while(true)std::cout << "xxxxxxxxxxxxxxxx";}')]
    for label,code in cases:
        result=run_judge(code,tests)
        assert result['passed'] is False,(label,result)
        print('PASS rejects '+label)
    # The untrusted process must not write rootfs or open an external network socket.
    isolation='''#include <fstream>
#include <iostream>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <unistd.h>
int main(){
 std::ofstream f("/forbidden");
 int fd=socket(AF_INET,SOCK_STREAM,0);
 sockaddr_in a{};a.sin_family=AF_INET;a.sin_port=htons(53);inet_pton(AF_INET,"1.1.1.1",&a.sin_addr);
 bool net=connect(fd,(sockaddr*)&a,sizeof(a))==0;
 std::cout << (!f && !net && getuid()!=0 ? "ok" : "unsafe");
}'''
    assert run_judge(isolation,tests)['passed']
    print('PASS non-root / read-only rootfs / no external network')
    print(f'All Docker acceptance checks passed in {time.monotonic()-start:.1f}s')


if __name__=='__main__':main()
