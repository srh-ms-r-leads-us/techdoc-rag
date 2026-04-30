# Case Study: a Retrieval-Augmented Generation (RAG) Chatbot for Technical Documentation

## Repository Structure Overview

### Folders

- `src/`: Core Python package; all production code (config, data processing, features, models, services, CLI).
- `tests/`: Unit and integration tests to validate functionality and ensure reliability.
- `scripts/`: Standalone scripts for running tasks such as training, deployment, or maintenance.
- `data/`: Local datasets (raw, processed, external); typically not version-controlled.
- `notebooks/`: Jupyter notebooks for exploration, prototyping, and analysis.
- `docs/`: Project documentation, architecture design, API specs, and experiment notes.
- `assets/`: Static resources such as images, diagrams, and sample outputs for demos or docs.
- `models/`: Saved model artifacts (e.g., .joblib, checkpoints); often ignored in Git.
- `logs/`: Runtime logs and debugging output; not tracked in version control.
- `docker/`: Containerization setup including Dockerfile and orchestration configs.

### Root Files

- `README.md`: Project overview, setup instructions, and usage guide.
- `LICENSE`: Legal license defining usage and distribution rights.
- `pyproject.toml`: Dependency management and build configuration.
- `uv.lock` / `poetry.lock`: Dependency lock files for reproducibility (optional).
- `.env.example`: Template for environment variables configuration.
- `.gitignore`: Specifies files and directories excluded from version control.
