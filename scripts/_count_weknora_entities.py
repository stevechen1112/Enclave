import subprocess

out = subprocess.check_output(
    ["docker", "exec", "WeKnora-neo4j", "cypher-shell", "-u", "neo4j", "-p", "password",
     "MATCH (n) WHERE any(l IN labels(n) WHERE l STARTS WITH 'ENTITY') RETURN count(n);"],
    text=True, stderr=subprocess.STDOUT, timeout=30,
)
print("ENTITY nodes:", out.strip())
rel = subprocess.check_output(
    ["docker", "exec", "WeKnora-neo4j", "cypher-shell", "-u", "neo4j", "-p", "password",
     "MATCH ()-[r]->() RETURN count(r);"],
    text=True, stderr=subprocess.STDOUT, timeout=30,
)
print("relationships:", rel.strip())
