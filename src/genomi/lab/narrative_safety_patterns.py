"""Compiled fail-closed patterns for unsafe clinical assertions."""

from __future__ import annotations

import re

_ERROR = "cannot contain a diagnosis or treatment directive"
_FORM_ERROR = "must use a declared research narrative form"
_RESEARCH_PROCESS_KINDS = {
    "meta",
    "plan_summary",
    "plan_role_objective",
    "plan_step_title",
    "plan_step_rationale",
    "execution_summary",
    "change_summary",
    "confirmation_need",
}

_INTERROGATIVE = re.compile(
    r"^(?:can|could|should|would|is|are|was|were|do|does|did|has|have|had|"
    r"what|which|who|whom|whose|when|where|why|how|may|might|will)\b",
    re.IGNORECASE,
)
_INTERNAL_QUESTION_UNIT = re.compile(r"[.!?;]|[\r\n]")
_CLAUSE_BOUNDARY = re.compile(
    r"(?:[.!?;,:—–]|\b(?:and|but|however|yet|whereas|while|because|"
    r"since|although|though|therefore|thus|so|as|when|before|after|"
    r"given\s+that|assuming\s+that|now\s+that)\b)",
    re.IGNORECASE,
)

_SOURCE_ATTRIBUTION = re.compile(
    r"\b(?:the\s+)?(?:issued\s+)?(?:laboratory\s+|clinical\s+)?"
    r"(?:report|record|study|paper|source|publication|database|authors?|"
    r"laboratory|clinician)\s+(?:states?|reports?|records?|documents?|"
    r"describes?|classifies?|labels?|lists?|notes?|says?|attributes?|"
    r"associates?)\b",
    re.IGNORECASE,
)

_CARE_ACTION = (
    r"(?:start|restart|stop|take|use|give|administer|prescribe|switch|increase|decrease|"
    r"continue|avoid|hold|receive|begin|initiate|discontinue|adjust|treat|undergo|"
    r"consider|choose|select|recommend|order|schedule)"
)
_IMPERATIVE_CARE_ACTION = re.compile(
    rf"(?:^|[.!?;,:—–]\s*|\b(?:and|then)\s+)"
    rf"(?:please\s+)?(?:do\s+not\s+|don't\s+|never\s+)?"
    rf"(?P<verb>{_CARE_ACTION})\b(?P<object>[^.!?;]{{0,140}})",
    re.IGNORECASE,
)
_SAFE_RESEARCH_OBJECT = re.compile(
    r"^\s*(?:(?:the|an?)\s+)?(?:(?:approved|available|pinned|public|supplied|"
    r"current|existing|relevant|consulted|recorded|reported|source-grounded|"
    r"unsupported|additional|independent|clinical|laboratory|disease-focused|"
    r"disease)\s+)*(?:evidence|data|context|profile|records?|sources?|"
    r"investigation|research|review|analysis|assessment|comparison|capability|"
    r"questions?|hypotheses|hypothesis|gaps?|brief|plan|workflow|retrieval|"
    r"search|validation|confirmation|findings?|observations?|citations?|"
    r"anchors?|results?|conclusions?)\b|"
    r"^\s*(?:(?:by|with)\s+)?(?:reviewing|using|assessing|comparing|retrieving|"
    r"validating|examining|investigating)\b",
    re.IGNORECASE,
)
_SAFE_RECOMMENDATION_OBJECT = re.compile(
    r"^\s*(?:(?:the|an?)\s+)?(?:(?:additional|independent|clinical|laboratory|"
    r"further|approved|public|evidence-based)\s+)*(?:review|testing|confirmation|"
    r"verification|validation|evaluation|assessment|research|evidence|analysis|"
    r"investigation|follow-up|questions?)\b|"
    r"^\s*(?:reviewing|assessing|validating|examining|investigating)\s+"
    r"(?:(?:the|an?|approved|available|public)\s+)*(?:evidence|data|records?|"
    r"sources?|profile|findings?|results?)\b",
    re.IGNORECASE,
)
_PATIENT_MODAL_ACTION = re.compile(
    rf"\b(?:the\s+patient|patient|you|the\s+individual|the\s+subject|they|he|"
    rf"she)\s+(?:should|must|ought\s+to|needs?\s+to|can(?:not|'t)?|"
    rf"could(?:not|n't)?|may|might|will|would|is\s+to)\s+(?:not\s+)?"
    rf"(?:be\s+)?(?:{_CARE_ACTION}|started|stopped|taken|used|given|administered|"
    rf"prescribed|switched|increased|decreased|continued|avoided|received|"
    rf"initiated|discontinued|adjusted|treated)\b",
    re.IGNORECASE,
)
_PATIENT_NEEDS_PRODUCT = re.compile(
    r"\b(?:the\s+patient|patient|you|the\s+individual|the\s+subject)\s+"
    r"(?:needs?|does\s+not\s+need|doesn't\s+need)\s+"
    r"(?!independent\s+confirmation\b|clinical\s+confirmation\b|review\b|"
    r"testing\b|evidence\b|follow-up\b|evaluation\b|assessment\b)\S+",
    re.IGNORECASE,
)
_DIRECT_RECOMMENDATION = re.compile(
    r"\b(?:we|i|genomilab|the\s+agent|the\s+system|the\s+patient's\s+team)\s+"
    r"(?:recommend|recommends|recommended|advise|advises|advised|urge|urges|"
    r"instruct|instructs|direct|directs)\s+(?P<object>[^.!?;]{1,120})",
    re.IGNORECASE,
)
_LABELLED_RECOMMENDATION = re.compile(
    r"(?:^|[.!?;,:—–]\s*)(?:recommended|preferred)\s*:\s*"
    r"(?P<object>[^.!?;]{1,100})",
    re.IGNORECASE,
)
_IMPERATIVE_DIAGNOSIS_OR_TREATMENT_REVIEW = re.compile(
    r"(?:^|[.!?;,:—–]\s*)(?:please\s+)?"
    r"(?:confirm|diagnose|establish|determine|select|choose|recommend)\s+"
    r"(?:(?:the|a|an)\s+)?(?:patient(?:'s|’s)\s+)?"
    r"(?:diagnosis|disease|condition|best\s+treatment|preferred\s+treatment|"
    r"treatment|therapy|medication|drug|regimen|dose)\b",
    re.IGNORECASE,
)
_LABELLED_CARE_DECISION = re.compile(
    r"(?:^|[.!?;]\s*)(?:first[- ]line|second[- ]line|preferred|recommended|"
    r"selected|chosen|best|standard)\s+(?:treatment|therapy|medication|drug|"
    r"regimen)\s*:\s*\S+",
    re.IGNORECASE,
)
_DECISION_TO_CARE = re.compile(
    r"\b(?:supports?|requires?|warrants?|justifies?|indicates?|"
    r"calls?\s+for|demands?)\b[^.!?;]{0,75}\b(?:starting|stopping|using|"
    r"taking|giving|administering|choosing|switching|initiating|discontinuing|"
    r"treatment(?!\s+(?:evidence|literature|research|review|analysis))|"
    r"therapy(?!\s+(?:evidence|literature|research|review|analysis))|"
    r"medication|drug|dose|regimen|clinical\s+action|care\s+changes?|"
    r"changes?\s+to\s+care)\b",
    re.IGNORECASE,
)
_NEGATED_DECISION = re.compile(
    r"\b(?:does|do|did|can|cannot|can't|could|couldn't|is|are|was|were|has|"
    r"have|had)\s+(?:not|n't)\s+(?:support|require|warrant|justify|indicate|"
    r"call\s+for|demand)\b",
    re.IGNORECASE,
)
_DOUBLE_NEGATIVE_DECISION = re.compile(
    r"\b(?:does|do|did|can|could|is|are|was|were|has|have|had)\s+"
    r"(?:not|n't)\s+(?:fail|fails|failed|lack|lacks|lacked)\s+to\b",
    re.IGNORECASE,
)
_CONFIRMATION_BEFORE_CARE = re.compile(
    r"\b(?:independent\s+|clinical\s+|laboratory\s+)?(?:confirmation|review|"
    r"testing|verification)\b[^.!?;]{0,65}\bbefore\b",
    re.IGNORECASE,
)
_CARE_PREDICATE = re.compile(
    r"\b(?P<subject>[a-z][a-z0-9'\-/]*(?:\s+[a-z][a-z0-9'\-/]*){0,6})\s+"
    r"(?:is|are|was|were|would\s+be|appears?\s+to\s+be|seems?\s+to\s+be)\s+"
    r"(?:not\s+)?(?:clinically\s+)?(?P<predicate>indicated|recommended|"
    r"appropriate|preferred|effective|beneficial|contraindicated)\b",
    re.IGNORECASE,
)
_SAFE_PROCESS_SUBJECT = re.compile(
    r"\b(?:confirmation|review|testing|test|evidence|evaluation|assessment|"
    r"consultation|follow-up|verification|validation|investigation|research|"
    r"analysis|question|association|claim|inference|causality|conclusion)\b",
    re.IGNORECASE,
)
_PRODUCT_MODAL_ACTION = re.compile(
    r"\b(?P<subject>[a-z][a-z0-9'\-/]*(?:\s+[a-z][a-z0-9'\-/]*){0,6})\s+"
    r"(?:should|must|needs?\s+to|is\s+to|ought\s+to)\s+(?:not\s+)?(?:be\s+)?"
    r"(?:started|stopped|used|given|administered|prescribed|switched|increased|"
    r"decreased|continued|avoided|initiated|discontinued|adjusted|received|"
    r"taken|treated)\b",
    re.IGNORECASE,
)
_BEST_TREATMENT = re.compile(
    r"\b(?:the\s+)?(?:best|preferred|recommended|appropriate|standard|"
    r"first[- ]line)\s+(?:treatment|therapy|medication|drug|regimen)\b"
    r"[^.!?;]{0,35}\b(?:is|would\s+be|should\s+be)\b|"
    r"\b[^.!?;]{1,50}\b(?:is|would\s+be)\s+(?:the\s+)?(?:best|preferred|"
    r"recommended|first[- ]line)\s+(?:treatment|therapy|medication|drug|"
    r"regimen)\b",
    re.IGNORECASE,
)
_PATIENT_BENEFIT = re.compile(
    r"\b[^.!?;]{1,70}\b(?:will|would)\s+(?:clinically\s+)?benefit\s+"
    r"(?:this|the)\s+(?:patient|individual|subject)\b",
    re.IGNORECASE,
)
_ELIGIBILITY = re.compile(
    r"\b(?:the\s+patient|patient|you|the\s+individual|the\s+subject)\s+"
    r"(?:is|are|appears?\s+to\s+be|seems?\s+to\s+be|may\s+be|might\s+be|"
    r"could\s+be)?\s*(?:eligible|qualifies?)\s+(?:for|to\s+(?:receive|start|"
    r"take|use|undergo|join|enroll\s+in))\b|"
    r"\b(?:finding|result|variant|mutation|profile)\b[^.!?;]{0,50}\b"
    r"(?:makes?\s+(?:the\s+)?patient\s+eligible|qualifies?\s+(?:the\s+)?"
    r"patient)\b",
    re.IGNORECASE,
)
_DOSING_STATEMENT = re.compile(
    r"\b(?:[a-z][a-z0-9'\-/]*(?:\s+[a-z][a-z0-9'\-/]*){0,5})\s+"
    r"(?:at|of|:)?\s*\d+(?:\.\d+)?\s*(?:mg|mcg|μg|g|ml|units?)\b|"
    r"(?:^|[.!?;,:]\s*)\d+(?:\.\d+)?\s*(?:mg|mcg|μg|g|ml|units?)\b",
    re.IGNORECASE,
)

_PATIENT_DIAGNOSIS = re.compile(
    r"\b(?:the\s+patient|patient|you|the\s+individual|the\s+subject)\s+"
    r"(?:[a-z]+ly\s+){0,3}(?:has|have|had|suffers?\s+from|"
    r"is\s+diagnosed\s+with|was\s+diagnosed\s+with|meets?\s+(?:the\s+)?"
    r"criteria\s+for|is\s+positive\s+for)\b",
    re.IGNORECASE,
)
_DIAGNOSIS_ASSERTION = re.compile(
    r"\b(?:the\s+)?diagnosis\s+(?:is|was|has\s+been)\b|"
    r"\bmakes?\s+(?:the\s+)?diagnosis\s+(?:certain|confirmed|definitive)\b|"
    r"\brules?\s+in\b|"
    r"(?:^|[.!?;]\s*)(?:patient\s+)?diagnosis\s*:\s*\S+|"
    r"\b[^.!?;,:—–]{1,55}\b(?:is|was)\s+(?:the\s+)?diagnosis\b",
    re.IGNORECASE,
)
_DIRECT_DIAGNOSIS_REQUEST = re.compile(
    r"(?:^|[.!?;,:—–]\s*)(?:please\s+)?(?:obtain|make|assign|give|"
    r"confirm|establish|determine)\s+(?:(?:a|the)\s+)?(?:new\s+)?diagnosis\b",
    re.IGNORECASE,
)
_EVIDENCE_ESTABLISHES = re.compile(
    r"\b(?:this|the|a|an)?\s*(?:evidence|finding|result|variant|mutation|"
    r"alteration|biomarker|test|profile|molecular\s+finding)\b"
    r"[^.!?;,:—–]{0,45}\b(?:confirms?|establish(?:es)?|proves?|"
    r"demonstrates?|shows?|means?|rules?\s+in)\b",
    re.IGNORECASE,
)
_THIS_ESTABLISHES = re.compile(
    r"\b(?:this|that|it)\s+(?:confirms?|establish(?:es)?|proves?|demonstrates?|"
    r"shows?|means?|rules?\s+in)\b",
    re.IGNORECASE,
)
_EVIDENCE_SUPPORTS_DIAGNOSIS = re.compile(
    r"\b(?:this|the|a|an)?\s*(?:evidence|finding|result|variant|mutation|"
    r"alteration|biomarker|test|profile|analysis|data)\b[^.!?;,:—–]{0,45}"
    r"\b(?:supports?|indicates?|warrants?|justifies?)\b"
    r"[^.!?;,:—–]{0,45}\b(?:the\s+|a\s+)?(?:diagnosis|diagnostic|"
    r"pathogenicity|actionability)\b",
    re.IGNORECASE,
)
_CLINICAL_STATUS = re.compile(
    r"\b(?:this|that|it|the\s+(?:variant|mutation|finding|result|test|evidence|"
    r"profile)|a\s+(?:variant|mutation|finding|result))\s+"
    r"(?:is|are|was|were|has\s+been|remains?|became)\s+(?:not\s+)?"
    r"(?:likely\s+)?(?:disease-causing|pathogenic|diagnostic|"
    r"medically\s+actionable|actionable|clinically\s+confirmed)\b|"
    r"\b(?:diagnostic\s+of|medically\s+actionable|clinically\s+confirmed)\b|"
    r"\b(?:variant|mutation|finding|result|test)\s+(?:is|was)\s+positive\s+for\b",
    re.IGNORECASE,
)
_NOMINAL_CLINICAL_STATUS = re.compile(
    r"\b(?:pathogenic|disease-causing|diagnostic|medically\s+actionable|"
    r"clinically\s+confirmed|confirmed|definitive|established)\b"
    r"(?:\s+[a-z0-9-]+){0,5}\s+"
    r"(?:variant|mutation|alteration|finding|result|diagnosis)\b|"
    r"\b(?:(?:[A-Z][A-Z0-9-]{1,20})\s+)?(?:variant|mutation|alteration|finding|"
    r"result)\b(?:\s+[a-z0-9-]+){0,4}\s+(?:as\s+)?(?:pathogenic|"
    r"disease-causing|diagnostic|medically\s+actionable|clinically\s+confirmed)\b",
    re.IGNORECASE,
)
_CLASSIFICATION_LABEL = re.compile(
    r"(?:^|[.!?;]\s*)(?:(?:acmg|amp|clinical|variant|molecular|laboratory)\s+)?"
    r"(?:classification|interpretation|conclusion|result)\s*:\s*"
    r"(?:likely\s+)?(?:pathogenic|disease-causing|diagnostic|actionable|"
    r"clinically\s+confirmed|positive)\b",
    re.IGNORECASE,
)
_CONFIRMED_FACT = re.compile(
    r"\b(?:diagnosis|condition|disease|result|finding|variant|mutation|test)\b"
    r"[^.!?;,:—–]{0,45}\b(?:is|are|was|were|has\s+been|have\s+been)\s+"
    r"(?:clinically\s+)?(?:confirmed|definitive|established)\b",
    re.IGNORECASE,
)
_MOLECULAR_CAUSALITY = re.compile(
    r"\b(?:this|that|the|a|an)?\s*(?:variant|mutation|gene|alteration|biomarker|"
    r"finding|result|[A-Z][A-Z0-9-]{1,20})\b[^.!?;,:—–]{0,35}\b"
    r"(?<!help\s)(?:causes?|caused|explains?|explained|accounts?\s+for|drives?|driven|"
    r"underlies?|is\s+(?:the\s+)?(?:cause|driver)\s+of|"
    r"is\s+responsible\s+for)\b|"
    r"\b[^.!?;,:—–]{1,80}\b(?:is|are|was|were)\s+"
    r"(?:caused|driven|explained)\s+by\s+(?:this|that|the|a|an)?\s*"
    r"(?:variant|mutation|gene|alteration|biomarker|finding|result|"
    r"[A-Z][A-Z0-9-]{1,20})\b",
    re.IGNORECASE,
)
_CAUSAL_ADJECTIVE = re.compile(
    r"\b(?:variant|mutation|gene|alteration|biomarker|finding|result|"
    r"[A-Z][A-Z0-9-]{1,20})\b[^.!?;,:—–]{0,35}\b"
    r"(?:is|are|was|were|appears?\s+to\s+be|seems?\s+to\s+be)\s+"
    r"(?:directly\s+)?causal\s+(?:for|in)\b",
    re.IGNORECASE,
)
_REVERSED_PATIENT_DIAGNOSIS = re.compile(
    r"\b(?:[A-Z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,7}|"
    r"the\s+(?:disease|condition|diagnosis))\s+(?:is|was|appears?\s+to\s+be|"
    r"seems?\s+to\s+be)\s+present\s+in\s+(?:this|the)\s+patient\b|"
    r"\b(?:[A-Z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,7})\s+"
    r"was\s+diagnosed\s+in\s+(?:this|the)\s+patient\b|"
    r"\bthe\s+clinical\s+picture\s+supports?\s+(?:a|the)\s+diagnosis\b",
    re.IGNORECASE,
)
_ALTERNATE_CAUSALITY = re.compile(
    r"\b(?:variant|mutation|gene|alteration|biomarker|finding|result)\b"
    r"[^.!?;,:]{0,35}\b(?:leads?\s+to|is\s+causative\s+(?:of|for)|"
    r"is\s+etiologic\s+(?:for|in))\b|"
    r"\b(?:disease|condition|phenotype|symptoms?)\b[^.!?;,:]{0,25}\b"
    r"results?\s+from\s+(?:this|the|a|an)?\s*(?:variant|mutation|gene|"
    r"alteration|biomarker|finding|result)\b",
    re.IGNORECASE,
)
_ALTERNATE_CLINICAL_STATUS = re.compile(
    r"\bpathogenicity\s+(?:is|was|has\s+been)\s+established\b|"
    r"\b(?:the\s+)?(?:molecular|variant|clinical)\s+classification\s+"
    r"(?:is|was)\s+(?:likely\s+)?pathogenic\b|"
    r"\b(?:the\s+)?(?:result|finding|variant|profile)\s+has\s+(?:clear\s+)?"
    r"clinical\s+utility\b|"
    r"\b(?:this|the)\s+(?:variant|finding|result|profile)\s+can\s+guide\s+"
    r"treatment\b",
    re.IGNORECASE,
)
_ALTERNATE_CARE_DECISION = re.compile(
    r"\btreatment\s+should\s+be\s+\S+|"
    r"\b[^.!?;,:]{1,70}\bis\s+(?:the\s+)?treatment\s+of\s+choice\b|"
    r"\b(?:the\s+)?patient\s+requires?\s+(?:chemotherapy|treatment|therapy|"
    r"medication|a\s+drug|a\s+regimen)\b|"
    r"\b(?:the\s+)?patient\s+can\s+(?:enroll|join|receive|start|take|use)\b|"
    r"\b[^.!?;,:]{1,70}\bbenefits?\s+(?:this|the)\s+patient\b",
    re.IGNORECASE,
)

_SAFE_UNRESOLVED_CLAIMS = (
    re.compile(
        r"\b(?:this|that|it|the\s+(?:variant|mutation|finding|result|test|"
        r"evidence|profile)|a\s+(?:variant|mutation|finding|result))\s+"
        r"(?:is|are|was|were|has\s+been|remains?)\s+not\s+(?:likely\s+)?"
        r"(?:disease-causing|pathogenic|diagnostic|medically\s+actionable|"
        r"actionable|clinically\s+confirmed)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:evidence|finding|result|variant|mutation|test|profile|analysis|"
        r"data)\b[^.!?;,:—–]{0,30}\b(?:does|do|did|can|cannot|can't|"
        r"could|couldn't|is|are|was|were|has|have|had)\s+(?:not|n't)\s+"
        r"(?:support|confirm|establish|prove|demonstrate|show|mean|indicate|"
        r"warrant|justify|require|rule\s+in)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:variant|mutation|gene|alteration|biomarker|finding|result|"
        r"[A-Z][A-Z0-9-]{1,20})\b[^.!?;,:—–]{0,25}\b"
        r"(?:may|might|could)\s+(?:potentially\s+)?(?:help\s+)?(?:be\s+)?"
        r"(?:disease-causing|pathogenic|diagnostic|actionable|cause|explain|"
        r"account\s+for|drive|underlie|be\s+causal)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:whether|if)\b[^.!?;,:—–]{0,45}\b(?:disease-causing|"
        r"pathogenic|diagnostic|actionable|clinically\s+confirmed|causes?|"
        r"explains?|confirms?|establishes?)\b",
        re.IGNORECASE,
    ),
)
_ASSERTION_LAUNDERING = re.compile(
    r"\bwhether\b[^.!?;]{0,80}\bdoes\s+not\s+change\b[^.!?;]{0,40}"
    r"\b(?:fact|conclusion)\s+that\b|"
    r"\b(?:not|never)\s+(?:false|untrue)\s+that\b|"
    r"\b(?:does|do|did|can|could|is|are|was|were|has|have|had)\s+"
    r"(?:not|n't)\s+(?:fail|fails|failed|lack|lacks|lacked)\s+to\s+"
    r"(?:confirm|establish|prove|demonstrate|show|support|indicate)\b",
    re.IGNORECASE,
)

_NO_CONFIRMATION_REQUIRED = re.compile(
    r"\b(?:no|without)\s+(?:additional\s+|further\s+|independent\s+|clinical\s+|"
    r"laboratory\s+)*(?:confirmation|review|testing|verification)\s+"
    r"(?:is\s+)?(?:needed|required|necessary)\b|"
    r"\b(?:confirmation|review|testing|verification)\s+(?:is|are|was|were)\s+"
    r"(?:not|no\s+longer)\s+(?:needed|required|necessary)\b|"
    r"\b(?:confirmation|review|testing|verification)\s+(?:is|are|was|were)\s+"
    r"unnecessary\b|\b(?:skip|omit|forego)\s+(?:the\s+)?(?:confirmation|review|"
    r"testing|verification)\b|"
    r"\b(?:confirmation|review|testing|verification)\s+(?:can|may|should)\s+be\s+"
    r"(?:skipped|omitted|foregone)\b|"
    r"\b(?:result|finding|variant|test|profile)\b[^.!?;]{0,35}\bneeds?\s+no\s+"
    r"(?:additional\s+|further\s+|independent\s+|clinical\s+|laboratory\s+)*"
    r"(?:confirmation|review|testing|verification)\b|"
    r"\b(?:confirmation|review|testing|verification)\s+need\s+not\s+be\b|"
    r"\bthere\s+(?:is|was)\s+no\s+need\s+for\s+(?:additional\s+|further\s+|"
    r"independent\s+|clinical\s+|laboratory\s+)*(?:confirmation|review|testing|"
    r"verification)\b|"
    r"\b(?:clinical\s+|laboratory\s+|independent\s+)?(?:confirmation|review|"
    r"testing|verification)\s+(?:is|was|appears?\s+to\s+be)\s+optional\b|"
    r"\b(?:result|finding|variant|test|profile)\b[^.!?;]{0,35}\brequires?\s+no\s+"
    r"(?:additional\s+|further\s+|independent\s+|clinical\s+|laboratory\s+|"
    r"follow-up\s+)*(?:confirmation|review|testing|verification)\b|"
    r"\b(?:review|evidence|finding|result|analysis)\s+(?:states?|indicates?|"
    r"suggests?|shows?)\b[^.!?;]{0,50}\b(?:confirmation|review|testing|"
    r"verification)\s+(?:is\s+)?optional\b",
    re.IGNORECASE,
)
_CONFIRMATION_FORM = re.compile(
    r"\b(?:confirm|confirmation|review|test|testing|evidence|verify|verification|"
    r"validate|validation|follow-up|assess|assessment|evaluate|evaluation|"
    r"determine|clarify|resolve|corroborate|corroboration|replicate|replication|"
    r"phenotype|assay|laboratory\s+report)\b",
    re.IGNORECASE,
)

_PRESUPPOSED_CLINICAL_FACT = re.compile(
    r"\b(?:the|this|that|a|an)\s+(?:confirmed|definitive|established|pathogenic|"
    r"disease-causing|diagnostic|actionable)\s+(?:diagnosis|disease|condition|"
    r"variant|mutation|finding|result)\b|"
    r"\bfrom\s+(?:the\s+)?(?:confirmed|definitive|established)\s+diagnosis\b",
    re.IGNORECASE,
)
_QUESTION_PREMISE = re.compile(
    r"(?:,\s*|\s+)(?:given(?:\s+that)?|assuming\s+that|now\s+that|because|"
    r"since|whereas|while|although|though|as|when|after|before)\s+",
    re.IGNORECASE,
)
_QUESTION_SECONDARY_CLAUSE = re.compile(
    r"(?:,|:|—|–|\b(?:and|but|yet)\b)\s*",
    re.IGNORECASE,
)
_DECLARATIVE_CLAUSE_START = re.compile(
    r"^\s*(?:(?:and|but|yet)\s+)?(?:the\s+)?(?:patient|individual|subject|"
    r"this|that|it|evidence|finding|result|variant|mutation|alteration|profile|"
    r"treatment|therapy|medication|drug|diagnosis|condition|disease|"
    r"[a-z][a-z0-9'-]*(?:\s+[a-z][a-z0-9'-]*){0,4})\s+"
    r"(?:[a-z]+ly\s+){0,2}(?:has|have|had|is|are|was|were|causes?|caused|"
    r"explains?|explained|confirms?|confirmed|establishes?|established|proves?|"
    r"proved|demonstrates?|demonstrated|shows?|showed|means?|meant|qualifies?|"
    r"qualified|supports?|supported|requires?|required|warrants?|warranted|"
    r"indicates?|indicated|should|must|needs?)\b",
    re.IGNORECASE,
)

# Positive, typed narrative forms.  The deny rules above remain useful as
# defence in depth, but acceptance is decided by these forms.  This matters at
# the research boundary: a novel way of making a clinical claim must fail closed
# instead of being accepted merely because it missed a blacklist expression.
_NARRATIVE_UNIT_BOUNDARY = re.compile(
    r"(?<=[.!?;])(?:[\"'\u201d\u2019])?\s+(?=[A-Z0-9\"'\u201c\u2018])|[\r\n]+"
)
_TYPED_PREFIX = re.compile(
    r"^(?P<label>Patient record observation|Patient-reported observation|"
    r"Patient observation|Source evidence|Model inference|Counterevidence|"
    r"Evidence limitation|Technical limitation|Conflict limitation|"
    r"Evidence gap|Gap|Conflicts|Gaps|Uncertainty)\s*:\s*(?P<body>.+)$",
    re.IGNORECASE | re.DOTALL,
)
_REPORTING_MARKER = re.compile(
    r"\b(?:reports?|reported|records?|recorded|documents?|documented|lists?|"
    r"listed|labels?|labelled|labeled|states?|stated|notes?|noted|describes?|"
    r"described|contains?|contained|identifies?|identified|found|classifies?|"
    r"classified|associates?|associated|shows?|showed|weighs?\s+against|"
    r"supports?|supported|"
    r"was\s+recorded|were\s+recorded|is\s+recorded|are\s+recorded)\b",
    re.IGNORECASE,
)
_SOURCE_OR_OBSERVATION_SUBJECT = re.compile(
    r"^(?:the\s+patient|patient|the\s+profile|the\s+(?:issued|laboratory|"
    r"clinical|scoped|approved|public|reported|synthetic|current)\s+"
    r"(?:report|record|source|study|paper|evidence|result|profile)|"
    r"the\s+(?:report|record|source|study|paper|publication|database|authors?|"
    r"laboratory|evidence|result|profile)|an?\s+(?:issued|laboratory|clinical|"
    r"public|reported|synthetic|computational|model)\s+(?:report|record|source|"
    r"study|paper|result|output)|current\s+source\s+evidence|source\s+[^ ]+|"
    r"the\s+scoped\s+sample\s+evidence|the\s+reported\s+finding|"
    r"the\s+source-grounded\s+relation|the\s+eligible\s+registered\s+relation|an?\s+(?:synthetic\s+)?literature\s+"
    r"fixture|an?\s+(?:derivative\s+)?(?:registered\s+)?relation)\b",
    re.IGNORECASE,
)
_CANDIDATE_MARKER = re.compile(
    r"\b(?:candidate|hypothes(?:is|es)|possible|possibly|may|might|could|"
    r"tentative|uncertain|unestablished|unresolved|research\s+candidate|"
    r"candidate\s+mechanism|model\s+inference|association\s+only|"
    r"supports?\s+recording)\b",
    re.IGNORECASE,
)
_CANDIDATE_SUBJECT = re.compile(
    r"^(?:the|this|that|an?)?\s*(?:(?:reported|molecular|source-grounded|"
    r"agent-authored|bounded|possible|personal|public|generic|refuting|uncertain|"
    r"registered)\s+)*"
    r"(?:variant|mutation|gene|finding|result|relation|association|mechanism|"
    r"overlap|inference|candidate|hypothesis|evidence|record|report|interpretation|"
    r"molecular\s+profile|model\s+output)\b",
    re.IGNORECASE,
)
_IDENTIFIER_CANDIDATE_SUBJECT = re.compile(
    r"^(?:rs\d+(?:\s+in\s+[A-Z][A-Z0-9-]{1,20})?|"
    r"[A-Z][A-Z0-9-]{1,20}\s+(?:variant|mutation|gene|finding|relation))\b",
)
_PATIENT_TENTATIVE_DIAGNOSIS = re.compile(
    r"\b(?:the\s+patient|patient|you|the\s+individual|the\s+subject)\s+"
    r"(?:may|might|could|appears?\s+to|seems?\s+to)\s+(?:possibly\s+)?"
    r"(?:have|has|suffer\s+from|be\s+diagnosed\s+with|meet\s+(?:the\s+)?"
    r"criteria\s+for|be\s+positive\s+for)\b|"
    r"\b(?:may|might|could)\s+(?:be\s+)?present\s+in\s+(?:this|the)\s+patient\b",
    re.IGNORECASE,
)
_LIMITATION_MARKER = re.compile(
    r"\b(?:does\s+not|do\s+not|did\s+not|cannot|can't|could\s+not|couldn't|"
    r"has\s+not|have\s+not|had\s+not|is\s+not|are\s+not|was\s+not|"
    r"were\s+not|must\s+not|no\b|lacks?|lacking|without|unavailable|"
    r"unresolved|unestablished|unknown|uncertain|not\s+checked|not\s+assessed|"
    r"not\s+(?:clinical|diagnostic|causal|pathogenic|actionable|treatment|"
    r"therapy|medication|disease)|"
    r"requires?|required|needs?|needed|remain(?:s|ed)?\s+(?:open|required|"
    r"unresolved|unestablished|uncertain)|open\s+requirement|as\s+open|"
    r"alone\s+must\s+not)\b",
    re.IGNORECASE,
)
_LIMITATION_SUBJECT = re.compile(
    r"^(?:the|this|that|an?|no|independent|clinical|laboratory|further|"
    r"additional|current)?\s*(?:(?:reported|molecular|source-grounded|"
    r"technical|clinical|primary|public|personal|eligible|approved|scoped|uncertain|"
    r"exact|separate|genotype-support|source-correction|literature|live-provider|"
    r"sample|recorded|causal|independent|patient-reported|direct)\s+)*"
    r"(?:evidence|finding|result|variant|mutation|relation|association|source|"
    r"record|report|fixture|status|link|analysis|interpretation|classification|pathogenicity|"
    r"causality|mechanism|clinical\s+relevance|clinical\s+significance|"
    r"causal\s+link|model\s+inference|variant\s+identity|consequence|zygosity|segregation|inheritance|"
    r"phenotype|conflict|consensus|gap|uncertainty|confirmation|validation|"
    r"verification|corroboration|replication|review|testing|profile|overlap|"
    r"draft|capability|resolution|GenomiLab|diagnosis|treatment\s+directive|"
    r"approved\s+context)\b",
    re.IGNORECASE,
)
_COUNTEREVIDENCE_MARKER = re.compile(
    r"\b(?:counterevidence|weighs?\s+against|refutes?|refuting|weakens?|"
    r"argues?\s+against|does\s+not\s+support|fails?\s+to\s+support|"
    r"contradicts?|inconsistent\s+with)\b",
    re.IGNORECASE,
)
_CONFLICT_MARKER = re.compile(
    r"\b(?:no\s+conflict|none|not\s+identified|not\s+recorded|conflict|"
    r"discord|contradict|consensus)\b",
    re.IGNORECASE,
)
_SYNTHETIC_RESEARCH_FRAGMENT = re.compile(
    r"^(?:Proposed\s+plan|Synthetic\s+(?:host-neutral\s+)?(?:plan|summary|"
    r"output)|Review(?:\s+a\s+synthetic\s+research\s+question)?|"
    r"This\s+is\s+a\s+synthetic\s+contract\s+observation)\.?$",
    re.IGNORECASE,
)
_SAFE_TITLE = re.compile(
    r"^(?:What\s+the\s+current\s+research\s+record\s+says\s+about\s+.+|"
    r"[^\r\n]{1,450}\b(?:review|brief|report|record|finding(?:s)?|evidence|"
    r"investigation|mechanism|profile|question|summary|analysis|assessment|"
    r"relation|research|draft)|Review)\.?$",
    re.IGNORECASE,
)
_UNSAFE_TITLE_TERM = re.compile(
    r"\b(?:diagnosis|diagnostic|treatment|therapy|medication|regimen|dose|"
    r"pathogenic|pathogenicity|actionable|causal|causative|etiologic|confirmed|"
    r"established|assigned|required|eligible|eligibility|best|chemotherapy|"
    r"immunotherapy|first[- ]line|recommendation|recommended|q\d+[a-z]*)\b",
    re.IGNORECASE,
)
_CLINICAL_DISEASE_TOKEN = re.compile(
    r"\b(?:ALS|cancer|carcinoma|sarcoma|syndrome|disease|disorder|diagnosis|"
    r"condition|leukemia|lymphoma|melanoma|diabetes|epilepsy|dementia|"
    r"neuropathy|myopathy|cardiomyopathy)\b",
    re.IGNORECASE,
)
_UNSAFE_TITLE_CLAIM = re.compile(
    r"\b(?:patient\s+has|patient\s+is\s+diagnosed|is\s+present|causes?|"
    r"leads?\s+to|causative|etiologic|patient\s+lives?\s+with|belongs?\s+to\s+"
    r"(?:this|the)\s+patient|definitive)\b",
    re.IGNORECASE,
)
_SAFE_OPERATION = re.compile(
    r"^(?P<verb>use|review|investigate|continue|avoid|begin|project|resolve|"
    r"retrieve|search|synthesize|register|record|preserve|curate|extract|"
    r"compare|evaluate|assess|validate|verify|clarify|determine|confirm|"
    r"check|keep|propose|ground|add|create|bind|link)\b"
    r"(?P<object>.*)$",
    re.IGNORECASE | re.DOTALL,
)
_RESEARCH_TARGET = re.compile(
    r"\b(?:approved|reported|resolved|current|original|independent|public|"
    r"source|evidence|profile|record|report|finding|variant|gene|identity|"
    r"representation|literature|relation|association|hypothesis|mechanism|"
    r"inference|observation|conflict|gap|uncertainty|confirmation|validation|"
    r"phenotype|inheritance|segregation|clinical\s+relevance|research|"
    r"investigation|question|context|claim|anchor|brief|plan|request|what\s+the\s+"
    r"investigation\s+cannot\s+yet\s+establish|"
    r"capabilit(?:y|ies)|results?|conclusions?|classification|reasoning|work|coverage|"
    r"literature|patient\s+facts|disease\s+relevance|disease\s+relation|"
    r"molecular\s+finding)\b",
    re.IGNORECASE,
)
_UNSAFE_OPERATION_TARGET = re.compile(
    r"\b(?:the\s+fact\s+that|first[- ]line|treatment\s+of\s+choice|best\s+"
    r"treatment|patient\s+has|patient\s+is\s+diagnosed|proceed\s+with|"
    r"start\s+[a-z0-9-]+|stop\s+[a-z0-9-]+|administer|prescribe|resume|"
    r"settle|issue\s+(?:a|the)\s+diagnosis|choose|favor|conclude|certify|"
    r"enroll|declare|authorize|endorse|prefer|approve|opt\s+for|mandate|"
    r"make\s+(?:chemotherapy|treatment|therapy|medication)|"
    r"call\s+(?:it|the\s+finding)|treatment-determining|trial\s+eligibility|"
    r"resuming?|restart|anoint|green[- ](?:lit|light(?:ed|ing)?)|"
    r"rubber[- ]stamp(?:ed|ing)?|crown|deem|sanction|bless|"
    r"legitimize)\b",
    re.IGNORECASE,
)
_SAFE_CHANGE = re.compile(
    r"^(?:added|clarified|synthesized|updated|recorded|created|prepared|"
    r"initial)\b",
    re.IGNORECASE,
)
_SAFE_CHANGE_OBJECT = re.compile(
    r"\b(?:question|evidence|profile|hypothesis|gap|brief|draft|plan|finding|"
    r"observation|uncertainty|relation|review|summary|research|approved|"
    r"candidate|source|reasoning)\b",
    re.IGNORECASE,
)
_UNSAFE_CHANGE_COMPLEMENT = re.compile(
    r"\b(?:that\s+the\s+patient\s+(?:has|lives?\s+with)|ALS\s+(?:is|was|"
    r"became|belongs?)|patient\s+(?:has|lives?\s+with)|pathogenicity\s+"
    r"(?:is|was|became)?\s*(?:established|confirmed)|treatment\s+of\s+choice|"
    r"assign(?:ing|ed)?\s+[A-Z][A-Za-z0-9-]*\s+to\s+the\s+patient|"
    r"declar(?:ing|ed)?|assert(?:ing|ed)?|anoint(?:ing|ed)?|"
    r"green[- ](?:lit|light(?:ed|ing)?)|rubber[- ]stamp(?:ed|ing)?|"
    r"crown(?:ing|ed)?|deem(?:ing|ed)?|sanction(?:ing|ed)?|bless(?:ing|ed)?|"
    r"legitimiz(?:ing|ed)?)\b",
    re.IGNORECASE,
)
_TOOL_FREE_PLAN = re.compile(r"^Tool-free\s+plan\b", re.IGNORECASE)
_NO_CLINICAL_CONCLUSION = re.compile(
    r"^No\s+(?:capability|domain\s+capability|model\s+inference|conflict|"
    r"diagnosis|treatment\s+directive|clinical\s+claim|tool|capability\s+call)",
    re.IGNORECASE,
)
_INDEPENDENT_META = re.compile(
    r"^(?:Independent\s+(?=[^.!?]*\b(?:request|schema|evidence-separation)\b)"
    r"(?=[^.!?]*\baudits?\b)[^.!?]*\b(?:was|were)\s+synthesized|"
    r"Independent\s+reasoning\s+validation\s+(?:(?:confirmed\s+(?:the\s+)?"
    r"(?:(?:eligible|approved|exact|recorded|supported)\s+)?(?:relation\s+)?"
    r"anchor\b)(?:\s+and\s+found\s+no\b[^.!?]*)?|found\s+no\b[^.!?]*)|"
    r"An\s+independent\s+template-selection\s+review\s+agreed\s+with\s+"
    r"(?:the\s+)?(?:supports|refutes|uncertain)\s+template)$",
    re.IGNORECASE,
)
_RESEARCH_GUARDRAIL = re.compile(
    r"^(?:retrieved|returned|reported|source-scoped|approved)\s+(?:claims?|"
    r"results?|findings?|evidence|observations?)\s+must\s+remain\s+"
    r"(?:source\s+evidence|research\s+observations?|candidate\s+hypotheses?)\b",
    re.IGNORECASE,
)
_CONFIRMATION_ACTION = re.compile(
    r"^(?:independently\s+)?(?P<verb>confirm|review|test|verify|validate|assess|"
    r"evaluate|determine|clarify|resolve|corroborate|replicate|obtain|check)\b"
    r"(?P<object>.+)$",
    re.IGNORECASE,
)
_CONFIRMATION_NOUN_PHRASE = re.compile(
    r"^(?:(?:additional|further|independent|clinical|laboratory|primary|"
    r"appropriate|current|usable|exact|reported|source)\s+)*"
    r"(?:confirmation|review|testing|verification|validation|evaluation|"
    r"assessment|evidence|counterevidence|corroboration|replication|"
    r"phenotype|assay|laboratory\s+report)\b",
    re.IGNORECASE,
)
_CONFIRMATION_EVIDENCE_OBJECT = re.compile(
    r"^(?:usable|additional|further|independent|current|primary|supporting|"
    r"counter|source|public|clinical|laboratory|orthogonal)\s+"
    r"(?:evidence|counterevidence|records?|sources?)\b",
    re.IGNORECASE,
)
_UNSAFE_FINITE_CONCLUSION = re.compile(
    r"\b(?:proves?|establishes?|confirms?\s+(?:the\s+)?diagnosis|"
    r"recommends?|requires?\s+(?:chemotherapy|treatment|therapy|medication)|"
    r"guides?\s+treatment|benefits?\s+(?:this|the)\s+patient|conclud(?:e|ed|es)|"
    r"assign(?:ed|s)?|declar(?:e|ed|es)|certif(?:y|ied|ies)|select(?:ed|s)?|"
    r"mandat(?:e|ed|es)|endorse(?:d|s)?|approv(?:e|ed|es)|prefer(?:red|s)?|"
    r"favor(?:ed|s)?|guarantee(?:d|s)?|settle(?:d|s)?|authoriz(?:e|ed|es)|"
    r"names?\b[^.!?;]{0,45}\btreatment\s+of\s+choice|anoint(?:ed|s)?|"
    r"green[- ](?:lit|light(?:ed|s)?)|rubber[- ]stamp(?:ed|s)?|"
    r"crown(?:ed|s)?|deem(?:ed|s)?|sanction(?:ed|s)?|"
    r"bless(?:ed|es)?|legitimiz(?:e|ed|es)|assert(?:ed|s)?)\b",
    re.IGNORECASE,
)
_DOUBLE_NEGATED_CLINICAL = re.compile(
    r"\b(?:cannot|can't|does\s+not|do\s+not|did\s+not|is\s+not|are\s+not|"
    r"was\s+not|were\s+not)\s+(?:not|non[- ]|un(?:necessary|confirmed|"
    r"pathogenic|resolved|established))\b",
    re.IGNORECASE,
)
_CONFIRMATION_DISAVOWAL = re.compile(
    r"\b(?:no|without)\s+(?:additional\s+|further\s+|independent\s+|"
    r"clinical\s+|laboratory\s+)*(?:validation|corroboration|replication|"
    r"evaluation|assessment)\s+(?:is\s+)?(?:needed|required|necessary)\b|"
    r"\b(?:confirmation|review|testing|verification|validation|corroboration|"
    r"replication|evaluation|assessment)\s+(?:is|are|was|were|would\s+be)\s+"
    r"(?:unnecessary|redundant|optional|not\s+(?:needed|required|necessary))\b|"
    r"\bno\s+further\s+(?:confirmation|review|testing|verification|validation|"
    r"corroboration|replication|evaluation|assessment)\b",
    re.IGNORECASE,
)
_UNSAFE_CONFIRMATION_TARGET = re.compile(
    r"(?:^|[,;:]\s*|\band\s+)(?:answer\s+yes|yes\b|approve|authorize|endorse|"
    r"favor|prefer|recommend|resume|start|stop|administer|prescribe|choose|"
    r"mandate|certify|declare|establish|confirm\s+(?:a|the)?\s*diagnosis)|"
    r"\b(?:treatment|therapy|medication|drug|chemotherapy|immunotherapy)\s+"
    r"(?:should|must|is\s+to)\s+be\b|\b(?:treatment\s+of\s+choice|"
    r"patient\s+(?:has|lives\s+with)|ALS\s+is\s+present|as\s+confirmed|"
    r"drug\s+suitability|\b\w+\s+fits\b)\b",
    re.IGNORECASE,
)
_CONFIRMATION_REVIEW_TARGET = re.compile(
    r"^(?:whether|what|which|how|current\s+primary\s+evidence|the\s+(?:current\s+)?"
    r"(?:primary\s+)?evidence|independent\s+(?:evidence|counterevidence|review)|"
    r"the\s+(?:exact|reported|original|approved|candidate|molecular|clinical)\s+"
    r"(?:finding|variant|result|record|report|profile|relation|evidence|"
    r"interpretation)|(?:clinical\s+)?relevance|source\s+(?:evidence|status)|"
    r"correction\s+or\s+retraction\s+status)\b",
    re.IGNORECASE,
)
_CONFIRMATION_IDENTITY_TARGET = re.compile(
    r"^(?:whether|what|which|how|the\s+exact|exact|the\s+reported|reported|"
    r"the\s+original|original|the\s+laboratory|laboratory|the\s+source|source|"
    r"the\s+variant|variant|the\s+finding|finding|the\s+result|result|the\s+"
    r"record|record|the\s+report|report|the\s+allele|allele|the\s+genotype|"
    r"genotype|the\s+identity|identity)\b",
    re.IGNORECASE,
)
_QUESTION_FORBIDDEN_DELIMITER = re.compile(
    r"[\[\]{}|]|=>|\([^)]*\)|\s/\s|[A-Za-z]/[A-Za-z]|:|\u2014|"
    r"\s[\u2013]\s|\b(?:plus|then)\b",
    re.IGNORECASE,
)
_QUESTION_EMBEDDED_CONCLUSION = re.compile(
    r"\b(?:the\s+answer\s+is|now\s+(?:that\s+)?(?:the\s+)?diagnosis|"
    r"diagnosis\s+is\s+(?:confirmed|established|definitive)|"
    r"patient\s+has\s+[a-z0-9]|patient\s+was\s+diagnosed|"
    r"individual\s+carries\s+[a-z0-9]|"
    r"variant\s+(?:causes?|is\s+causative)|proceed\s+with\s+(?:treatment|"
    r"therapy|chemotherapy)|do\s+it\s+now|yes\s+is\s+the\s+answer|"
    r"definitely\s+yes|act\s+immediately|execute\s+that\s+decision|"
    r"pathology\s+confirms?|result\s+equals?|ALS\s+(?:is|became)\s+"
    r"(?:confirmed|present|definitive|established)|ALS\s+represents?\s+the\s+"
    r"diagnosis|affirmative|unquestionably|certainly|stands?\s+proven|"
    r"pathogenicity\s+settled|definitive\s+ALS)\b",
    re.IGNORECASE,
)
_QUESTION_CLINICAL_PREMISE = re.compile(
    r"\b(?:following|once|with|owing\s+to|on\s+the\s+basis\s+that|in\s+light\s+"
    r"of|after|because|given(?:\s+that)?|assuming\s+that|now\s+that)\b"
    r"[^?]{0,100}\b(?:diagnosis|diagnostic|pathogenic|confirmed|definitive|"
    r"established|caused|causal|treatment)\b",
    re.IGNORECASE,
)
_QUESTION_APPENDED_ASSERTION = re.compile(
    r"(?:,|\b(?:and|or)\b)\s*(?:the\s+)?(?:patient|individual|subject|"
    r"pathology|[A-Z][A-Za-z0-9-]*(?:\s+[A-Za-z][A-Za-z0-9-]*){0,5}|"
    r"pembrolizumab|chemotherapy|treatment|therapy)\s+"
    r"(?:is|are|was|were|has|have|carries?|works?|confirms?|equals?|became|"
    r"resume|start|stop|requires?|qualifies?)\b|"
    r",\s*(?:yes|definitely\s+yes|affirmative)\b",
    re.IGNORECASE,
)
_QUESTION_APPENDED_CARE_ACTION = re.compile(
    r",\s*(?:please\s+)?(?:resume|restart|start|stop|take|use|give|administer|"
    r"prescribe|switch|increase|decrease|continue|avoid|hold|receive|begin|"
    r"initiate|discontinue|adjust|treat|undergo|choose|approve|authorize)\b",
    re.IGNORECASE,
)
_RESEARCH_CLAUSE_JOIN = re.compile(
    r",?\s+(?:but|while|whereas|however)\s+|,\s+yet\s+|"
    r",\s+and\s+(?=(?:an?|the|this|that|[A-Z][A-Za-z0-9-]*)\b"
    r"[^,;]{0,55}\b(?:is|are|was|were|has|have|records?|reports?|shows?|"
    r"supports?|exists?|causes?|leads?))",
    re.IGNORECASE,
)
