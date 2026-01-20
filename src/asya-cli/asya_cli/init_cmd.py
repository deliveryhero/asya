"""Initialize a new Asya actor project with boilerplate files."""

import argparse
from pathlib import Path


# --- Templates ---

TEMPLATE_HANDLER = """
def process(payload: dict) -> dict:
    # Your logic here
    # Example: Enrich the payload with a result
    return {
        **payload,
        "greeting": f"Hello, {payload.get('name', 'World')}!"
    }
""".lstrip()

TEMPLATE_DOCKERFILE = """
FROM python:3.13-slim

WORKDIR /app
COPY handler.py /app/

# Install dependencies (uncomment if needed)
# RUN pip install --no-cache-dir requests

CMD ["python3", "-c", "import handler; print('Handler loaded')"]
""".lstrip()

TEMPLATE_ACTOR_YAML = """
apiVersion: asya.sh/v1alpha1
kind: AsyncActor
metadata:
  name: {actor_name}
spec:
  transport: sqs # or kafka, rabbitmq, etc.
  scaling:
    minReplicas: 0
    maxReplicas: 10
    queueLength: 5 # for each 5 messages in queue create 1 new pod
  workload:
    kind: Deployment
    template:
      spec:
        containers:
        - name: asya-runtime
          image: my-hello-actor:latest
          imagePullPolicy: IfNotPresent
          env:
          - name: ASYA_HANDLER
            value: "handler.process"
          - name: PYTHONPATH
            value: /app
          - name: AWS_ACCESS_KEY_ID
            value: "test"
          - name: AWS_SECRET_ACCESS_KEY
            value: "test"
          - name: AWS_REGION
            value: "us-east-1"
""".lstrip()

# --- Logic ---


def generate_files(target_dir: Path, actor_name: str, force: bool = False):
    target_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "handler.py": TEMPLATE_HANDLER,
        "Dockerfile": TEMPLATE_DOCKERFILE,
        "actor.yaml": TEMPLATE_ACTOR_YAML.format(actor_name=actor_name),
    }

    for filename, content in files.items():
        file_path = target_dir / filename
        if file_path.exists() and not force:
            print(f"Skipped {filename} (already exists). Use --force to overwrite.")
            continue

        with open(file_path, "w") as f:
            f.write(content)
        print(f"Created {filename}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="asya init", description="Initialize a new Asya actor project with boilerplate files."
    )
    parser.add_argument("name", help="Name of the actor (used for directory and resource names)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing files")

    parsed_args = parser.parse_args(argv)

    cwd = Path.cwd()
    target_dir = cwd / parsed_args.name

    print(f"Initializing Asya actor '{parsed_args.name}' in {target_dir}...")
    generate_files(target_dir, parsed_args.name, parsed_args.force)
    print("\nDone! To get started:")
    print(f"  cd {parsed_args.name}")
    print("  docker build -t my-actor:v1 .")


if __name__ == "__main__":
    main()
