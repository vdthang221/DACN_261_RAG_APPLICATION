"""Container-only C++17 runner. Never execute this on the application host."""
import json
import os
import resource
import signal
import subprocess
import tempfile


def execute(command, stdin, timeout, output_limit):
    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_limit, output_limit))
        resource.setrlimit(resource.RLIMIT_CPU, (timeout, timeout + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        source.write(stdin.encode())
        source.seek(0)
        process = subprocess.Popen(command, stdin=source, stdout=out, stderr=err,
                                   start_new_session=True, preexec_fn=limits,
                                   env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"})
        timed_out = False
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
        out.seek(0)
        err.seek(0)
        return process.returncode, out.read(8192).decode(errors="replace"), err.read(8192).decode(errors="replace"), timed_out


def main():
    payload = json.load(__import__('sys').stdin)
    with tempfile.TemporaryDirectory(dir="/tmp") as work:
        os.chdir(work)
        with open("main.cpp", "w", encoding="utf-8") as file:
            file.write(payload["code"])
        rc, _, error, timeout = execute(["g++", "-std=c++17", "-O2", "-pipe", "main.cpp", "-o", "program"], "", 20, 16 * 1024 * 1024)
        if rc or timeout:
            return {"passed": False, "compile_error": "Biên dịch quá thời gian." if timeout else error, "tests": []}
        results = []
        for test in payload["tests"]:
            rc, actual, error, timeout = execute([work + "/program"], test["input"], 2, 8192)
            passed = not timeout and rc == 0 and actual.split() == test["expected"].split()
            results.append({"passed": passed, "actual": actual, "expected": test["expected"],
                            "input": test["input"], "error": "Quá thời gian (2 giây)." if timeout else (error or ("Lỗi runtime / vượt giới hạn output." if rc else ""))})
        return {"passed": all(t["passed"] for t in results), "compile_error": "", "tests": results}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False))
