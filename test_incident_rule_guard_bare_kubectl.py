"""Incident test. 2026-08-28, session a0d64ea4, crew#66: a bare `kubectl get ds -n observability-agent`
on the laptop hit the dead k3d-estate context (connection refused on 127.0.0.1:6445) and the reply
graded the estate BLIND while the cluster was fine. Founder: "it shouldn't, don't repeat mistakes ...
solve once and forever." Rule bare_kubectl in policy/command.rego names bin/idp-kube. Proved both ways."""
import importlib.util
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rule_guard", HERE / "rule-guard.py")
rg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rg)


def _verdict(cmd: str):
    return rg.decide(cmd)


def test_incident_bare_kubectl_is_refused_and_names_the_one_path():
    for cmd in (
        "kubectl get ds -n observability-agent",
        "kubectl get pods -n observability 2>&1 | tail -12",
        "cd /x && kubectl logs deploy/signoz -n observability",
        "kubectl -n edge describe svc traefik",
        "kubectl apply -f platform/edge/kyverno.yaml",
    ):
        v = _verdict(cmd)
        assert v is not None, cmd
        assert "bin/idp-kube" in v[1], cmd


def test_incident_estate_path_explicit_kubeconfig_and_local_subcommands_pass():
    for cmd in (
        "bin/idp-kube get pods -n observability",
        "KUBECONFIG=/tmp/kc kubectl get nodes -o json",
        "kubectl kustomize platform/observability | grep storageClass",
        "kubectl config get-contexts -o name",
        "kubectl version --client",
        "kubectl get pods  # kubectl-local-intended",
    ):
        assert _verdict(cmd) is None, cmd
