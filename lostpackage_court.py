# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }
from genlayer import *
from dataclasses import dataclass
import json

@allow_storage
@dataclass
class Claim:
    buyer: str
    seller: str
    order_id: str
    courier: str
    tracking_url: str
    buyer_evidence_url: str
    buyer_description: str
    seller_evidence_url: str
    claim_amount: u256
    status: str
    verdict: str
    refund_amount: u256
    reasoning: str

class LostPackageCourt(gl.Contract):
    claim_counter: u256
    claims: TreeMap[u256, Claim]

    def __init__(self):
        self.claim_counter = u256(0)

    @gl.public.write
    def create_claim(
        self,
        seller: str,
        order_id: str,
        courier: str,
        tracking_url: str,
        buyer_evidence_url: str,
        buyer_description: str,
        claim_amount: u256
    ) -> u256:
        claim_id = self.claim_counter
        self.claims[claim_id] = Claim(
            buyer=str(gl.message.sender_address),
            seller=seller,
            order_id=order_id,
            courier=courier,
            tracking_url=tracking_url,
            buyer_evidence_url=buyer_evidence_url,
            buyer_description=buyer_description,
            seller_evidence_url="",
            claim_amount=claim_amount,
            status="OPEN",
            verdict="PENDING",
            refund_amount=u256(0),
            reasoning="",
        )
        self.claim_counter = claim_id + u256(1)
        return claim_id

    @gl.public.write
    def add_seller_evidence(self, claim_id: u256, seller_evidence_url: str):
        claim = self.claims[claim_id]
        assert str(gl.message.sender_address) == claim.seller, "Only seller can add evidence"
        assert claim.status == "OPEN", "Claim already resolved"
        claim.seller_evidence_url = seller_evidence_url
        self.claims[claim_id] = claim

    @gl.public.write
    def resolve_claim(self, claim_id: u256):
        claim = self.claims[claim_id]
        assert claim.status == "OPEN", "Already resolved"
        claim_mem = gl.storage.copy_to_memory(claim)

        def leader_fn():
            def safe_render(url: str) -> str:
                if url == "":
                    return "NO_EVIDENCE"
                try:
                    page = gl.nondet.web.render(url, mode="text")
                    text = str(page)[:3500]
                    if text.strip() == "":
                        return "EMPTY_PAGE"
                    return text
                except Exception:
                    return "LOAD_FAILED"

            buyer_text = safe_render(claim_mem.buyer_evidence_url)
            tracking_text = safe_render(claim_mem.tracking_url)
            seller_text = "NO_EVIDENCE"
            if claim_mem.seller_evidence_url != "":
                seller_text = safe_render(claim_mem.seller_evidence_url)

            # PROMPT FINAL: Keyword-based, deterministik, anti-UNDETERMINED
            prompt = f"""
            You are a deterministic shipping dispute judge. Read the evidence text carefully.

            ORDER: {claim_mem.order_id}
            COURIER: {claim_mem.courier}
            BUYER SAYS: {claim_mem.buyer_description}

            --- BUYER EVIDENCE TEXT ---
            {buyer_text}

            --- TRACKING EVIDENCE TEXT ---
            {tracking_text}

            --- SELLER EVIDENCE TEXT ---
            {seller_text}

            DECISION RULES - Follow in order, check keywords (case-insensitive):

            RULE 1 - DELIVERED:
            If SELLER EVIDENCE contains ANY of these: "DELIVERED", "DITERIMA", "TANDA TANGAN", "SIGNED", "SUDAH SAMPAI", "RECEIVED", "FOTO PENERIMA", "PROOF OF DELIVERY"
            -> Return DELIVERED

            RULE 2 - LOST:
            Else if TRACKING or BUYER EVIDENCE contains ANY of these: "STUCK", "LOST", "HILANG", "TIDAK DITEMUKAN", "NOT FOUND", "TIDAK BERGERAK", "NO UPDATE", "RETURNED"
            AND SELLER EVIDENCE is NO_EVIDENCE or LOAD_FAILED or EMPTY_PAGE
            -> Return LOST

            RULE 3 - INCONCLUSIVE:
            Else -> Return INCONCLUSIVE

            IMPORTANT: Do NOT guess. Only use keywords above.
            Return ONLY one word, no punctuation, no explanation, no JSON:
            DELIVERED or LOST or INCONCLUSIVE
            """
            result = gl.nondet.exec_prompt(prompt)
            text = str(result).upper()
            if "DELIVERED" in text:
                return "DELIVERED"
            if "LOST" in text:
                return "LOST"
            return "INCONCLUSIVE"

        verdict = gl.eq_principle.strict_eq(leader_fn)

        if verdict == "LOST":
            refund_pct = 100
            reasoning = "Evidence shows tracking STUCK / LOST, no seller delivery proof found. Refund 100%."
        elif verdict == "DELIVERED":
            refund_pct = 0
            reasoning = "Seller evidence contains DELIVERED / DITERIMA / proof of delivery. Package delivered. Refund 0%."
        else:
            verdict = "INCONCLUSIVE"
            refund_pct = 50
            reasoning = "Evidence does not contain clear DELIVERED or LOST keywords. Refund 50%."

        refund = (claim.claim_amount * u256(refund_pct)) // u256(100)
        claim.verdict = verdict
        claim.refund_amount = refund
        claim.reasoning = reasoning
        claim.status = "RESOLVED"
        self.claims[claim_id] = claim

    @gl.public.view
    def get_claim(self, claim_id: u256) -> str:
        c = self.claims[claim_id]
        return json.dumps({
            "buyer": c.buyer,
            "seller": c.seller,
            "order_id": c.order_id,
            "status": c.status,
            "verdict": c.verdict,
            "refund_amount": str(c.refund_amount),
            "reasoning": c.reasoning,
        })
