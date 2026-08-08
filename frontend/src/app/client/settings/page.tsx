"use client";

import { ProfileView } from "@/components/profile/profile-view";

/**
 * Client Profile.
 *
 * The route stays `/client/settings` because it is baked into the GitHub App
 * return path and into existing links; only the label changed to "Profile".
 *
 * This used to also render the full GitHub App connection panel and a Circle
 * wallet card with its own balance and refresh button. Both duplicated
 * surfaces that already exist — the GitHub page and the top-bar wallet
 * popover — so the page now shows account facts and links out for management.
 */
export default function ClientProfilePage() {
  return <ProfileView workspace="client" />;
}
