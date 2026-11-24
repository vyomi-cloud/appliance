# Courses

Every Vyomi course, and the Python project that goes with it, lives in this folder. This is a standing guideline.

## Layout

```
courses/
  <course-slug>/                 e.g. vyomi-labs-facilities-agent
    README.md
    <cloud>/                     aws | gcp | azure (or one folder if the course is cloud-neutral)
      01-<layer>/ ... 13-<layer>/   one folder per layer: its code files, exactly as the course shows and deploys them, plus a README
      run_all.sh  requirements.txt  .env.example  .devcontainer/
```

## Rules

1. A new course gets its own folder here. Nothing course-related is committed anywhere else in the repo.
2. The code in the layer folders is generated from the course data (`vyomilabs/content/build_project.py`), never hand-edited, so the course, Deploy and GitHub are one source of truth.
3. A change to a lab block means regenerating the project in the same commit.
4. Each project must run on its own when checked out (README, requirements, devcontainer).
5. The course UI links to these folders: "Open in editor", "Open in Codespaces" and "View on GitHub".

## Standalone mirror

The learner's "Open in editor", "Open in Codespaces" and "View on GitHub" buttons must open only the course project, never the whole appliance.
Each course is therefore also published as its own repository, `vyomi-cloud/<course-slug>`, a mirror of `courses/<course-slug>/` (cloud folders at the root).
Publish it with `scripts/sync_course_repo.sh <course-slug> --push` (owner go required). The appliance copy stays the source of truth.
