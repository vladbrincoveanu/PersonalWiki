from dataclasses import dataclass, field


@dataclass
class Document:
    raw_text: str
    content_type: str  # "paper" | "article" | "tweet" | "video"
    images: list[bytes] = field(default_factory=list)
