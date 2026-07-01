"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function PCPRedirectPage() {
  const router = useRouter();
  useEffect(() => { router.replace("/pcp/workspace"); }, [router]);
  return null;
}
