import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";

const SCROLL_THRESHOLD = 48;

export function useChatScroll(messages: unknown[], busy: boolean) {
  const containerRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const autoScrollRef = useRef(true);
  const [showScrollButton, setShowScrollButton] = useState(false);

  const isNearBottom = useCallback(() => {
    const el = containerRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight <= SCROLL_THRESHOLD;
  }, []);

  const scrollToBottom = useCallback((behavior: ScrollBehavior = "auto") => {
    const el = containerRef.current;
    if (!el) return;
    const top = el.scrollHeight - el.clientHeight;
    if (behavior === "smooth") {
      el.scrollTo({ top, behavior: "smooth" });
    } else {
      el.scrollTop = top;
    }
  }, []);

  const syncScrollState = useCallback(() => {
    const nearBottom = isNearBottom();
    autoScrollRef.current = nearBottom;
    setShowScrollButton(!nearBottom && messages.length > 0);
  }, [isNearBottom, messages.length]);

  const handleScroll = useCallback(() => {
    syncScrollState();
  }, [syncScrollState]);

  const handleScrollToBottom = useCallback(() => {
    autoScrollRef.current = true;
    setShowScrollButton(false);
    scrollToBottom("smooth");
  }, [scrollToBottom]);

  useLayoutEffect(() => {
    if (messages.length === 0) {
      autoScrollRef.current = true;
      setShowScrollButton(false);
      return;
    }
    if (autoScrollRef.current) {
      scrollToBottom("auto");
    }
    syncScrollState();
  }, [messages, busy, scrollToBottom, syncScrollState]);

  useEffect(() => {
    const container = containerRef.current;
    const bottom = bottomRef.current;
    if (!container || !bottom) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        const atBottom = entry.isIntersecting;
        autoScrollRef.current = atBottom;
        setShowScrollButton(!atBottom && messages.length > 0);
      },
      {
        root: container,
        threshold: 0,
        rootMargin: `0px 0px ${SCROLL_THRESHOLD}px 0px`,
      }
    );

    observer.observe(bottom);
    return () => observer.disconnect();
  }, [messages.length]);

  useEffect(() => {
    const el = messagesRef.current;
    if (!el) return;

    const observer = new ResizeObserver(() => {
      if (autoScrollRef.current) {
        scrollToBottom("auto");
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [messages.length, scrollToBottom]);

  return {
    containerRef,
    bottomRef,
    messagesRef,
    showScrollButton,
    handleScroll,
    handleScrollToBottom,
  };
}
