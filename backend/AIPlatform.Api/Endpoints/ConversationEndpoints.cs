using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

public static class ConversationEndpoints
{
    public static IEndpointRouteBuilder MapConversationEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/api/platform/conversations");

        group.MapGet("",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/conversations"));

        group.MapPost("",
            async (IHttpClientFactory f) => await AiProxy.PostEmpty(f, "/conversations"));

        group.MapGet("/{conversationId}/messages",
            async (string conversationId, IHttpClientFactory f) =>
                await AiProxy.Get(f, $"/conversations/{Uri.EscapeDataString(conversationId)}/messages"));

        group.MapPut("/{conversationId}",
            async (string conversationId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Put(r, f, $"/conversations/{Uri.EscapeDataString(conversationId)}"));

        group.MapDelete("/{conversationId}",
            async (string conversationId, IHttpClientFactory f) =>
                await AiProxy.Delete(f, $"/conversations/{Uri.EscapeDataString(conversationId)}"));

        return app;
    }
}
