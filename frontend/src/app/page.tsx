"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Loading } from "@/components/ui";
import { useMe } from "@/lib/api";

export default function Home() {
  const { user, signedOut } = useMe();
  const router = useRouter();
  useEffect(() => {
    if (user) router.replace("/call/");
    else if (signedOut) router.replace("/login/");
  }, [user, signedOut, router]);
  return <Loading label="Opening VoiceOps AI" />;
}
