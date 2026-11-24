# Courses

Every Vyomi course, and the Python project that goes with it, lives in this folder. This is a standing guideline.

## Layout

```
courses/
  <course-slug>/                 e.g. vyomi-labs-facilities-agent
    README.md
    <cloud>/                     aws | gcp | azure (or one folder if the course is cloud-neutral)
      app/                       the code, exactly as the course shows and deploys it
      chapters/                  one README per chapter, steps in order
      run_all.sh  requirements.txt  .env.example  .devcontainer/
```

## Rules

1. A new course gets its own folder here. Nothing course-related is committed anywhere else in the repo.
2. The code in `app/` is generated from the course data (`vyomilabs/content/build_project.py`), never hand-edited, so the course, Deploy and GitHub are one source of truth.
3. A change to a lab block means regenerating the project in the same commit.
4. Each project must run on its own when checked out (README, requirements, devcontainer).
5. The course UI links to these folders: "Open in editor", "Open in Codespaces" and "View on GitHub".
