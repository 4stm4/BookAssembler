import re

CONTINUATION_WORDS = {
    "en": (
        r"the|a|an|of|in|to|for|and|or|is|are|by|on|with|from|that|which|as|"
        r"but|not|if|at|be|has|have|this|than|may|can|also|when|each|into|"
        r"between|all|more|both|they|their|these|it|such|its|was|were|been"
    ),
    "ru": (
        r"и|в|на|с|по|к|из|за|о|у|от|для|до|не|что|как|это|но|а|или|"
        r"при|его|её|их|он|она|мы|вы|все|так|уже|ещё|бы|же|ли|между"
    ),
    "de": (
        r"der|die|das|und|in|von|zu|mit|auf|für|an|ist|den|dem|ein|eine|"
        r"als|auch|es|des|sich|nicht|werden|bei|nach|aus|über|durch"
    ),
    "fr": (
        r"le|la|les|de|du|des|un|une|et|en|à|dans|pour|par|sur|avec|"
        r"est|sont|qui|que|ce|cette|il|elle|nous|vous|ils|pas|plus"
    ),
    "es": (
        r"el|la|los|las|de|del|un|una|y|en|por|para|con|que|es|"
        r"son|se|al|como|su|sus|más|pero|no|todo|esta|este"
    ),
}


def get_continuation_pattern(lang: str) -> re.Pattern | None:
    words = CONTINUATION_WORDS.get(lang)
    if not words:
        return None
    return re.compile(rf"\b({words})\s*$", re.IGNORECASE)
