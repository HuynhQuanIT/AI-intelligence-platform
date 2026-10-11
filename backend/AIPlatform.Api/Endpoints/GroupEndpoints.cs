using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

/// <summary>Quản lý nhóm người dùng (chỉ admin; ai-service kiểm tra quyền).</summary>
public static class GroupEndpoints
{
    public static IEndpointRouteBuilder MapGroupEndpoints(this IEndpointRouteBuilder app)
    {
        var groups = app.MapGroup("/api/platform/groups");

        groups.MapGet("",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/groups"));

        groups.MapPost("",
            async (HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, "/groups"));

        groups.MapGet("/{groupId}",
            async (string groupId, IHttpClientFactory f) =>
                await AiProxy.Get(f, $"/groups/{Uri.EscapeDataString(groupId)}"));

        groups.MapPut("/{groupId}",
            async (string groupId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Put(r, f, $"/groups/{Uri.EscapeDataString(groupId)}"));

        groups.MapDelete("/{groupId}",
            async (string groupId, IHttpClientFactory f) =>
                await AiProxy.Delete(f, $"/groups/{Uri.EscapeDataString(groupId)}"));

        groups.MapPut("/{groupId}/members",
            async (string groupId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Put(r, f, $"/groups/{Uri.EscapeDataString(groupId)}/members"));

        return app;
    }
}
