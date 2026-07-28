import type { SpecialistAgent } from "../models/types";

/**
 * Pro subscription placeholder.
 *
 * Deliberately does not take payment: there's no billing integration yet, so
 * the CTA states that plainly rather than dead-ending on a broken checkout.
 * Wire a provider here (Stripe Checkout → webhook → set the `tier` custom
 * claim) and the rest of the gating already works.
 */
export default function UpgradeDialog({
  agent,
  tier,
  onClose,
}: {
  agent: SpecialistAgent | null;
  tier: string;
  onClose: () => void;
}) {
  return (
    <div className="modal-scrim" onClick={onClose}>
      <div className="upgrade-card" onClick={(e) => e.stopPropagation()}>
        <button className="upgrade-x" onClick={onClose} title="Close">✕</button>

        <div className="upgrade-glyph">◢◤</div>
        <h2 className="upgrade-title">NEXUS PRO</h2>
        <p className="upgrade-lede">
          {agent
            ? `${agent.label} is a PRO specialist unit. Upgrade to deploy it.`
            : "Unlock the full specialist roster and a far larger monthly allowance."}
        </p>

        <div className="upgrade-plans">
          <div className="plan">
            <div className="plan-name">FREE</div>
            <div className="plan-price">$0<span className="plan-per">/mo</span></div>
            <ul className="plan-perks">
              <li>Core chat model</li>
              <li>Image generation</li>
              <li>Conversation history + memory</li>
              <li className="plan-perk-off">Specialist agents</li>
            </ul>
            <button className="plan-cta plan-cta-current" disabled>
              {tier === "free" ? "CURRENT PLAN" : "FREE TIER"}
            </button>
          </div>

          <div className="plan plan-featured">
            <div className="plan-name">PRO</div>
            <div className="plan-price">$—<span className="plan-per">/mo</span></div>
            <ul className="plan-perks">
              <li>Everything in Free</li>
              <li>All specialist agents + their tools</li>
              <li>MCP connectors</li>
              <li>Higher monthly call quota</li>
            </ul>
            <button className="plan-cta" disabled title="Billing isn't wired up yet">
              ⚡ COMING SOON
            </button>
          </div>
        </div>

        <p className="upgrade-note">
          Billing isn't live yet. An admin can grant PRO from the control plane
          (ADMIN → USERS → tier) in the meantime.
        </p>
      </div>
    </div>
  );
}
