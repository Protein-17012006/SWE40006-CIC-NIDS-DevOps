"""Locust users for the load test that runs during staging and production deployments.

Each user loads the page shell, the static files it names and the health check, waiting 1 to 5
seconds between requests. Streamlit draws pages over a WebSocket that Locust does not speak, so
page speed is judged by the page_render metric instead (NFR-01). Run it from the repository
root: locust -f tests/load/locustfile.py --host http://<load balancer>:<port>
"""

import random

from locust import HttpUser, between, task

from tests.load.shell import static_paths


class Viewer(HttpUser):
    wait_time = between(1, 5)

    def on_start(self) -> None:
        self.assets: list[str] = []
        with self.client.get("/", name="/", catch_response=True) as response:
            self.assets = static_paths(response.text or "")
            if not self.assets:
                response.failure("the page shell lists no static files")

    @task(3)
    def shell(self) -> None:
        self.client.get("/", name="/")

    @task(2)
    def health(self) -> None:
        self.client.get("/_stcore/health", name="/_stcore/health")

    @task(1)
    def asset(self) -> None:
        if self.assets:
            self.client.get(random.choice(self.assets), name="/static/*")
