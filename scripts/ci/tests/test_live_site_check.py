"""Post-deploy live check: workflow wiring and the HTTP comparison."""

import http.server
import re
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts/ci"))

import verify_live_site  # noqa: E402

SHARED = (ROOT / ".github/workflows/site.yml").read_text()


def job(name):
    match = re.search(rf"^  {name}:\n((?:(?:    .*)?\n)*)", SHARED + "\n", re.M)
    return match.group(1)


class LiveCheckWorkflowTests(unittest.TestCase):
    def test_deploy_reports_whether_it_deployed(self):
        deploy = job("deploy")
        self.assertIn("deployed: ${{ steps.fresh.outputs.deploy }}", deploy)
        self.assertIn(
            "previous_root_keys: ${{ steps.publish.outputs.previous_root_keys }}",
            deploy,
        )
        self.assertLess(
            deploy.index("list-objects-v2"), deploy.index("publish_site.sh")
        )
        self.assertIn('select(test("^(assets|images)/") | not)', deploy)

    def test_verify_runs_after_real_deploys_without_credentials(self):
        verify = job("verify")
        self.assertIn("if: needs.deploy.outputs.deployed == 'true'", verify)
        self.assertIn("needs: [check, deploy]", verify)
        self.assertRegex(verify, r"permissions:\n      contents: read\n    steps:")
        self.assertNotIn("id-token", verify)
        self.assertNotIn("secrets.", verify)
        self.assertIn('"apps/$SITE/dist" "$PREVIOUS_ROOT_KEYS"', verify)
        self.assertIn("live_site_browser.cjs", verify)

    def test_alert_only_opens_issues_and_runs_no_actions(self):
        alert = job("alert")
        self.assertIn(
            "if: always() && (needs.verify.result == 'failure' || "
            "(needs.deploy.outputs.deployed == 'true' && "
            "needs.deploy.result != 'success'))",
            alert,
        )
        self.assertIn("needs: [deploy, verify]", alert)
        self.assertRegex(alert, r"permissions:\n      issues: write\n    steps:")
        self.assertNotRegex(alert, r"\buses:")
        self.assertIn('--assignee "$OWNER"', alert)

    def test_callers_pass_their_own_domain(self):
        for site in ("oconnordev", "drumrollworld"):
            locals_tf = (ROOT / f"infra/aws/{site}/locals.tf").read_text()
            zone = re.search(r'zone_name\s*=\s*"([^"]+)"', locals_tf).group(1)
            caller = (ROOT / f".github/workflows/{site}-site.yml").read_text()
            self.assertIn(f"url: https://{zone}\n", caller)
            self.assertIn("issues: write", caller)

    def test_cache_rules_match_publication(self):
        publish = (ROOT / "scripts/ci/publish_site.sh").read_text()
        for pattern in verify_live_site.IMMUTABLE:
            self.assertIn(pattern.pattern, publish)

    def test_expected_headers_come_from_configuration(self):
        for site in ("oconnordev", "drumrollworld"):
            headers = verify_live_site.expected_headers(site)
            self.assertIn(
                headers["content-security-policy"],
                (ROOT / f"infra/aws/{site}/site.tf").read_text(),
            )
            self.assertTrue(headers["permissions-policy"].startswith("accelerometer="))


class LiveCheckHttpTests(unittest.TestCase):
    RELEASE = {"index.html": b"<html>new</html>", "404.html": b"missing", "a.css": b"x"}

    def serve(
        self, live, headers, missing_body, missing_status, stale, failing, redirect
    ):
        requests = {"a.css": 0}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                key = self.path.lstrip("/") or "index.html"
                if redirect and key.startswith("live-check-missing-"):
                    self.send_response(302)
                    self.send_header("location", "/redirected-missing")
                    self.end_headers()
                    return
                status, body = 200, live.get(key)
                if key == "a.css":
                    requests["a.css"] += 1
                    if requests["a.css"] <= failing:
                        self.send_error(503)
                        return
                    if requests["a.css"] <= stale:
                        body = None
                if body is None:
                    status, body = missing_status, missing_body
                self.send_response(status)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("cache-control", verify_live_site.cache_control(key))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def check(
        self,
        live=None,
        headers=None,
        missing_body=b"missing",
        missing_status=404,
        stale=0,
        failing=0,
        redirect=False,
        previous="[]",
        timeout=0,
    ):
        with tempfile.TemporaryDirectory() as temp:
            for key, body in self.RELEASE.items():
                (Path(temp) / key).write_bytes(body)
            url = self.serve(
                {**self.RELEASE, **(live or {})},
                headers or verify_live_site.expected_headers("oconnordev"),
                missing_body,
                missing_status,
                stale,
                failing,
                redirect,
            )
            verify_live_site.verify(
                "oconnordev", url, temp, previous, timeout, interval=0
            )

    def test_matching_release_passes(self):
        self.check()

    def test_retries_every_file_while_the_release_propagates(self):
        self.check(stale=3, timeout=30)

    def test_retries_server_errors_until_the_deadline(self):
        self.check(failing=3, timeout=30)

    def test_removed_root_files_must_return_the_404_page(self):
        self.check(previous='["index.html", "removed.html"]')

    def test_changed_file_wrong_header_or_404_fails(self):
        wrong = {
            **verify_live_site.expected_headers("oconnordev"),
            "x-frame-options": "SAMEORIGIN",
        }
        for case in (
            {"live": {"a.css": b"changed"}},
            {"headers": wrong},
            {"missing_body": b"wrong 404 page"},
            {"missing_status": 200},
            {"stale": 1000},
            {"failing": 1000},
            {"redirect": True},
            {"live": {"removed.html": b"stale"}, "previous": '["removed.html"]'},
        ):
            with self.subTest(case=case), self.assertRaises(RuntimeError):
                self.check(**case)


if __name__ == "__main__":
    unittest.main()
