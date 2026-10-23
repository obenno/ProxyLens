from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_management_stays_private_and_cpamp_is_the_only_queue_consumer():
    stack = yaml.safe_load((ROOT / "compose.yaml").read_text())
    services = stack["services"]
    published = {name for name, service in services.items() if service.get("ports")}
    assert published == {"gateway", "api", "keycloak"}
    for name in published:
        assert all(port.startswith("127.0.0.1:") for port in services[name]["ports"])
    for name in ("postgres", "keycloak-db", "cliproxyapi", "cpamp"):
        assert "ports" not in services[name]
    assert stack["networks"]["backend"]["internal"] is True
    assert stack["networks"]["provider"]["internal"] is True
    assert services["cpamp"]["environment"]["USAGE_COLLECTOR_MODE"] == "http"
    assert services["cpamp"]["environment"]["CPA_UPSTREAM_URL"] == "http://cliproxyapi:8317"
    assert services["cpamp"]["environment"]["CPA_MANAGEMENT_KEY_FILE"].startswith("/run/secrets/")
    for role in ("api", "gateway", "worker"):
        assert "cpa_management_key" not in services[role]["secrets"]
        assert not any("COLLECTOR" in key for key in services[role]["environment"])


def test_persistent_state_secret_mounts_health_and_dependency_graph():
    stack = yaml.safe_load((ROOT / "compose.yaml").read_text())
    services = stack["services"]
    for name, service in services.items():
        if not service.get("build"):
            assert "@sha256:" in service["image"], f"{name}: unpinned upstream image"
        if name != "cpa-init":
            assert service["healthcheck"]["test"], f"{name}: missing healthcheck"
        for dependency, policy in service.get("depends_on", {}).items():
            assert dependency in services
            assert policy["condition"] in {"service_healthy", "service_completed_successfully"}
        granted = set(service.get("secrets", []))
        assert granted <= stack["secrets"].keys()
        for key, value in service.get("environment", {}).items():
            if key.endswith("_FILE"):
                assert value.startswith("/run/secrets/")
                assert value.removeprefix("/run/secrets/") in granted
    state_mounts = {
        "postgres": "postgres_data:/var/lib/postgresql/data",
        "keycloak-db": "keycloak_db_data:/var/lib/postgresql/data",
        "cliproxyapi": "cpa_auth:/root/.cli-proxy-api",
        "cpamp": "cpamp_data:/data",
    }
    for service, mount in state_mounts.items():
        assert mount in services[service]["volumes"]
        assert mount.split(":")[0] in stack["volumes"]
    assert "cpa_config:/config" in services["cliproxyapi"]["volumes"]
    assert services["cliproxyapi"]["depends_on"]["cpa-init"] == {
        "condition": "service_completed_successfully"
    }
    for service in services.values():
        for mount in service.get("volumes", []):
            source = mount.split(":")[0]
            if source.startswith("./"):
                assert (ROOT / source).is_file(), f"missing bind source: {source}"
