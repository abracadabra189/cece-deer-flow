"""Shared heading numbering for DOCX and PDF renderers."""

from __future__ import annotations


def cn_number(value: int) -> str:
    digits = "零一二三四五六七八九"
    if value <= 0:
        return str(value)
    if value < 10:
        return digits[value]
    if value < 20:
        return "十" + (digits[value % 10] if value % 10 else "")
    if value < 100:
        return digits[value // 10] + "十" + (digits[value % 10] if value % 10 else "")
    return str(value)


class Numbering:
    def __init__(self, mode: str = "chapter"):
        self.mode = mode if mode in {"chapter", "article", "none"} else "chapter"
        self.h1 = 0
        self.h2 = 0
        self.h3 = 0

    def prefix(self, level: int) -> str:
        if self.mode == "none":
            return ""
        if self.mode == "article":
            if level == 1:
                self.h1 += 1
                self.h2 = 0
                self.h3 = 0
                return f"第{cn_number(self.h1)}条　"
            if level == 2:
                self.h2 += 1
                self.h3 = 0
                return f"{self.h1}.{self.h2} "
            self.h3 += 1
            return f"{self.h1}.{self.h2}.{self.h3} "
        if level == 1:
            self.h1 += 1
            self.h2 = 0
            self.h3 = 0
            return f"{cn_number(self.h1)}、"
        if level == 2:
            self.h2 += 1
            self.h3 = 0
            return f"{self.h1}.{self.h2} "
        self.h3 += 1
        return f"{self.h1}.{self.h2}.{self.h3} "
