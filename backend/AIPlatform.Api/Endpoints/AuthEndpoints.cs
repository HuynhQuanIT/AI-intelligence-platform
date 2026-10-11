using AIPlatform.Api.Services;

namespace AIPlatform.Api.Endpoints;

/// <summary>
/// Đăng ký, đăng nhập, quên mật khẩu và quản lý người dùng. Gateway chỉ chuyển tiếp;
/// ai-service kiểm tra mật khẩu, OTP, JWT và quyền.
/// </summary>
public static class AuthEndpoints
{
    private static readonly string[] PublicPostPaths =
    {
        "register/start", "register/verify", "register/complete",
        "forgot/start", "forgot/verify", "forgot/reset",
    };

    // Các endpoint đặt/đọc cookie refresh (httpOnly) nên cần chuyển Cookie và Set-Cookie.
    private static readonly string[] CookiePostPaths = { "login", "refresh", "logout" };

    public static IEndpointRouteBuilder MapAuthEndpoints(this IEndpointRouteBuilder app)
    {
        var auth = app.MapGroup("/api/platform/auth");

        foreach (var path in PublicPostPaths)
        {
            var target = "/auth/" + path;
            auth.MapPost("/" + path,
                async (HttpRequest r, IHttpClientFactory f) =>
                    await AiProxy.Post(r, f, target));
        }

        foreach (var path in CookiePostPaths)
        {
            var target = "/auth/" + path;
            auth.MapPost("/" + path,
                async (HttpContext ctx, IHttpClientFactory f) =>
                    await AiProxy.PostWithCookies(ctx, f, target));
        }

        // Đổi mật khẩu cần đăng nhập (Authorization được chuyển tiếp) và trả cookie refresh mới.
        auth.MapPost("/password",
            async (HttpContext ctx, IHttpClientFactory f) =>
                await AiProxy.PostWithCookies(ctx, f, "/auth/password"));

        auth.MapGet("/me",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/auth/me"));

        var users = app.MapGroup("/api/platform/users");

        users.MapGet("",
            async (IHttpClientFactory f) => await AiProxy.Get(f, "/users"));

        users.MapGet("/{userId}",
            async (string userId, IHttpClientFactory f) =>
                await AiProxy.Get(f, $"/users/{Uri.EscapeDataString(userId)}"));

        users.MapPost("/{userId}/password",
            async (string userId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, $"/users/{Uri.EscapeDataString(userId)}/password"));

        users.MapPost("/{userId}/approve",
            async (string userId, IHttpClientFactory f) =>
                await AiProxy.PostEmpty(f, $"/users/{Uri.EscapeDataString(userId)}/approve"));

        users.MapPost("/{userId}/deactivate",
            async (string userId, IHttpClientFactory f) =>
                await AiProxy.PostEmpty(f, $"/users/{Uri.EscapeDataString(userId)}/deactivate"));

        users.MapDelete("/{userId}",
            async (string userId, IHttpClientFactory f) =>
                await AiProxy.Delete(f, $"/users/{Uri.EscapeDataString(userId)}"));

        users.MapPost("/{userId}/email",
            async (string userId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, $"/users/{Uri.EscapeDataString(userId)}/email"));

        users.MapPost("/{userId}/quota",
            async (string userId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, $"/users/{Uri.EscapeDataString(userId)}/quota"));

        users.MapPost("/{userId}/role",
            async (string userId, HttpRequest r, IHttpClientFactory f) =>
                await AiProxy.Post(r, f, $"/users/{Uri.EscapeDataString(userId)}/role"));

        return app;
    }
}
