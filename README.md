# forest3d
Methods for generating 3D models of forest inventory plots and co-registering plot data with canopy height rasters and point clouds.

## Development

Open the repo in a dev container. Copy a template before your first build:

```bash
cp .devcontainer/cpu/devcontainer.example.json .devcontainer/cpu/devcontainer.json
# or, for CUDA:
cp .devcontainer/gpu/devcontainer.example.json .devcontainer/gpu/devcontainer.json
```

Your `devcontainer.json` is gitignored, so you can add your own extensions or mounts to it.

Run tasks with pixi, e.g. `pixi run test`, `pixi run lint`, or `pixi run ci`.
