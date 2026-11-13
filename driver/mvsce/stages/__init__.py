"""The stages, in build order.

A stage module defines NAME, TITLE, run(ctx) and verify(ctx). Its result
is the content of dasd/ when it ends. verify is the stage's manifest: the
stage counts as done only when it passes.
"""
from . import s1_starter, s2_dlibs

STAGES = [s1_starter, s2_dlibs]


def by_name(name):
    for stage in STAGES:
        if stage.NAME == name:
            return stage
    raise KeyError(name)
