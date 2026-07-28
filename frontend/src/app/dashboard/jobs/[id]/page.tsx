import { redirect } from "next/navigation";

export default async function LegacyJobRedirect({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  redirect(`/client/jobs/${id}`);
}
