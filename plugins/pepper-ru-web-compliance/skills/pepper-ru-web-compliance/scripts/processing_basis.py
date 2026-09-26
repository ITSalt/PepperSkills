"""Conservative extraction of declared bases, never a legal determination."""
import re

PURPOSES = {
    "analytics": r"аналитик\w*|статистик\w*",
    "ads": r"реклам\w*|маркетинг\w*",
    "session_recording": r"вебвизор\w*|запис\w* сесси\w*",
    "fraud_prevention": r"мошеннич\w*|безопасност\w*",
}
BASES = {
    "consent_declared": r"(?:на основании|по|с)\s+согласи\w*",
    "legitimate_interest_declared": r"законн\w* интерес\w*|п\.?\s*7\s*ч\.?\s*1\s*ст\.?\s*6",
    "contract_declared": r"(?:исполнени\w*|заключени\w*)\s+договор\w*",
}


def classify_activities(documents, observed):
    result = []
    for activity in observed:
        candidates, evidence = set(), []
        for url, text in documents:
            # Split only explicit clause boundaries; an ambiguous combined clause
            # must not assign one purpose's basis to another purpose.
            clauses = re.split(r"[\n;]+|(?<=[.!?])\s+(?=[А-ЯЁA-Z])|,\s*(?:а\s+)?(?=аналитик|реклам|маркетинг)", text, flags=re.I)
            for clause in clauses:
                low = clause.lower()
                purposes = {p for p, pattern in PURPOSES.items() if re.search(pattern, low)}
                named_services = {a["service"] for a in observed if a["service"].lower() in low}
                service_match = activity["service"] in named_services
                if named_services and not service_match:
                    continue
                if purposes and activity["purpose"] not in purposes:
                    continue
                if not purposes and not service_match:
                    continue
                bases = {b for b, pattern in BASES.items() if re.search(pattern, low)}
                if not bases:
                    continue
                negated = bool(re.search(r"\b(?:не|без|нельзя|отсутств\w*)\b", low))
                ambiguous = len(bases) != 1 or len(purposes) > 1 or negated
                value = "UNKNOWN" if ambiguous else next(iter(bases))
                candidates.add(value)
                evidence.append({"kind": "text", "url": url,
                                 "detail": f"{activity['service']} / {activity['purpose']}: кандидат основания",
                                 "snippet": clause.strip()})
        declared = next(iter(candidates)) if len(candidates) == 1 else "UNKNOWN"
        result.append({**activity, "declared_basis": declared, "verified_basis": None,
                       "verification_status": "UNKNOWN", "evidence": evidence})
    return result
