import { Suspense } from "react";
import { Loader2 } from "lucide-react";
import { ChatView } from "@/components/chat/chat-view";

async function Conversation({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ChatView key={id} conversationId={id} />;
}

export default function ConversationPage(props: PageProps<"/c/[id]">) {
  return (
    <Suspense
      fallback={
        <div className="flex h-full items-center justify-center text-muted-foreground">
          <Loader2 className="size-4 animate-spin text-brand" />
        </div>
      }
    >
      <Conversation params={props.params} />
    </Suspense>
  );
}
