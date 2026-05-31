export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const TELEGRAM_TOKEN = "8971008749:AAEReTyPwSHxcYMCmcoLfGf9yUP4ttgJvpw";
    const ADMIN_CHAT_ID = 989655080;

    // Handle webhook (incoming updates from Telegram)
    if (request.method === "POST" && url.pathname === "/webhook") {
      try {
        const update = await request.json();
        
        // If it's a message from someone else, reply "Нет доступа"
        if (update.message && update.message.chat) {
          const chatId = update.message.chat.id;
          
          if (chatId !== ADMIN_CHAT_ID) {
            const replyUrl = `https://api.telegram.org/bot${TELEGRAM_TOKEN}/sendMessage`;
            await fetch(replyUrl, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                chat_id: chatId,
                text: "Нет доступа"
              })
            });
          }
        }
        return new Response("OK", { status: 200 });
      } catch (err) {
        return new Response("Error processing webhook", { status: 500 });
      }
    }

    // Proxy requests to Telegram API
    // E.g., /sendDocument, /deleteMessage
    const telegramUrl = `https://api.telegram.org/bot${TELEGRAM_TOKEN}${url.pathname}${url.search}`;
    
    // Copy the request to forward it
    const requestOptions = {
      method: request.method,
      headers: request.headers,
    };
    
    if (request.method !== "GET" && request.method !== "HEAD") {
      requestOptions.body = request.body;
    }

    const tgResponse = await fetch(telegramUrl, requestOptions);
    
    // Return the response back to the client
    const responseBody = await tgResponse.arrayBuffer();
    return new Response(responseBody, {
      status: tgResponse.status,
      headers: tgResponse.headers
    });
  }
};