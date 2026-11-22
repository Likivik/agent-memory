# mnemobun — Nix packaging (P8)
#
# Follows the official uv2nix hello-world template (pyproject-nix/build-system-pkgs era):
# the uv.lock is the single source of dependency truth; Nix builds a venv from it.
#   packages.<system>.mnemobun  — venv with all workspace entry points
#   checks.<system>.mnemobun-tests — unit tests without network (uv --offline)
# Fleet use: import the overlay or add packages.mnemobun to environment.systemPackages.

{
  description = "mnemobun: deterministic claim/standing memory engine for agents";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";

    pyproject-nix = {
      url = "github:pyproject-nix/pyproject.nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    uv2nix = {
      url = "github:pyproject-nix/uv2nix";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    pyproject-build-systems = {
      url = "github:pyproject-nix/build-system-pkgs";
      inputs.pyproject-nix.follows = "pyproject-nix";
      inputs.uv2nix.follows = "uv2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs =
    {
      self,
      nixpkgs,
      pyproject-nix,
      uv2nix,
      pyproject-build-systems,
      ...
    }:
    let
      inherit (nixpkgs) lib;
      forAllSystems = lib.genAttrs lib.systems.flakeExposed;

      workspace = uv2nix.lib.workspace.loadWorkspace { workspaceRoot = ./.; };

      overlay = workspace.mkPyprojectOverlay {
        sourcePreference = "wheel";
      };

      # Some locked wheels (e.g. jieba) rely on setuptools without declaring it —
      # PEP-517-strict Nix builds refuse that where uv pip tolerated it.
      pyprojectOverrides = final: prev: {
        jieba = prev.jieba.overrideAttrs (old: {
          build-system = (old.build-system or [ ]) ++ [ final.setuptools ];
        });
      };

      pythonSets = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python313;
        in
        (pkgs.callPackage pyproject-nix.build.packages {
          inherit python;
        }).overrideScope
          (
            lib.composeManyExtensions [
              pyproject-build-systems.overlays.wheel
              overlay
              pyprojectOverrides
            ]
          )
      );
    in
    {
      packages = forAllSystems (system: {
        mnemobun = pythonSets.${system}.mkVirtualEnv "mnemobun-env" workspace.deps.default;
        default = pythonSets.${system}.mkVirtualEnv "mnemobun-env" workspace.deps.default;
      });

      devShells = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          virtualenv = pythonSets.${system}.mkVirtualEnv "mnemobun-dev-env" workspace.deps.all;
        in
        {
          default = pkgs.mkShell {
            packages = [
              virtualenv
              pkgs.uv
              pkgs.ruff
            ];
            env = {
              UV_NO_SYNC = "1";
              UV_PYTHON = pythonSets.${system}.python.interpreter;
              UV_PYTHON_DOWNLOADS = "never";
            };
            shellHook = ''
              unset PYTHONPATH
              export REPO_ROOT=$(git rev-parse --show-toplevel)
            '';
          };
        }
      );

      checks = forAllSystems (
        system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          virtualenv = pythonSets.${system}.mkVirtualEnv "mnemobun-check-env" workspace.deps.dev;
        in
        {
          mnemobun-tests = pkgs.runCommand "mnemobun-tests"
            {
              nativeBuildInputs = [ virtualenv ];
              src = self;
            }
            ''
              export HOME=$(mktemp -d)
              cp -r $src src && cd src && chmod -R u+w .
              python -m pytest tests/unit -q -p no:cacheprovider
              touch $out
            '';
        }
      );
    };
}
