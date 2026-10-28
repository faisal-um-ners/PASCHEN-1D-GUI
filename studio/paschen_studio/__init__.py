"""PASCHEN-1D Studio - graphical workbench for the PASCHEN-1D plasma solver.

The studio is an *additive* layer: it never modifies the PASCHEN-1D source
tree.  It reads the solver's own configuration dataclasses to build its forms,
and it runs simulations only through the solver's public API
(``config_loader.load_simulation_case``, ``validation.validate_simulation_config``
and ``paschen_1d.run_simulation``) in a separate worker process.
"""

__version__ = "1.0.0"

APP_NAME = "PASCHEN-1D Studio"
APP_ORG = "PASCHEN-1D"
APP_TAGLINE = "Gas breakdown & discharge simulation workbench"
APP_DESCRIPTION = (
    "One-dimensional drift-diffusion-Poisson plasma solver with multi-mechanism "
    "surface emission and flexible external-circuit coupling."
)
MODEL_SUFFIX = ".p1d.json"
MODEL_FORMAT = "paschen-studio-model/1"

PAPER_TITLE = (
    "PASCHEN-1D: A one-dimensional fluid plasma solver with multi-mechanism "
    "surface emission and flexible external circuit coupling"
)
PAPER_AUTHORS = "Asif Iqbal, Yves Heri, Bingqing Wang, Lan Jin, Md Arifuzzaman Faisal, Peng Zhang"
PAPER_JOURNAL = "Computer Physics Communications (2026)"
PAPER_URL = "https://www.sciencedirect.com/science/article/pii/S0010465526003863"
ARXIV_URL = "https://arxiv.org/abs/2608.07721"
REPO_URL = "https://github.com/pbis-umich/PASCHEN-1D"
STUDIO_REPO_URL = "https://github.com/faisal-um-ners/PASCHEN-1D-Temp"

BIBTEX = """@article{iqbal2026paschen1d,
  title   = {PASCHEN-1D: A one-dimensional fluid plasma solver with multi-mechanism
             surface emission and flexible external circuit coupling},
  author  = {Iqbal, Asif and Heri, Yves and Wang, Bingqing and Jin, Lan and
             Faisal, Md Arifuzzaman and Zhang, Peng},
  journal = {Computer Physics Communications},
  year    = {2026},
  url     = {https://www.sciencedirect.com/science/article/pii/S0010465526003863}
}"""
