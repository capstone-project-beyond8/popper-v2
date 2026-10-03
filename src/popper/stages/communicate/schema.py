"""Structured manuscript prose and figure references."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class FigureRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    node_id: str
    file: str
    caption: str
    section: Literal["data_methods", "exploratory", "main", "robustness"]


class Writeup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    abstract: str
    introduction: str
    data: str
    exploration: str
    hypothesis: str
    methods: str
    results: str
    robustness: str
    discussion: str
    conclusion: str
    figures: list[FigureRef]
