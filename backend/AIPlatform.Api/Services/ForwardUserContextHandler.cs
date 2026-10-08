namespace AIPlatform.Api.Services;

/// <summary>
/// Chuyển tiếp thông tin người dùng của request hiện tại sang ai-service: tiêu đề Authorization
/// (JWT, ai-service là nơi kiểm tra) và IP máy khách (để giới hạn đăng nhập/OTP theo IP).
/// </summary>
public sealed class ForwardUserContextHandler : DelegatingHandler
{
    private readonly IHttpContextAccessor _accessor;

    public ForwardUserContextHandler(IHttpContextAccessor accessor)
    {
        _accessor = accessor;
    }

    protected override Task<HttpResponseMessage> SendAsync(
        HttpRequestMessage request, CancellationToken cancellationToken)
    {
        var ctx = _accessor.HttpContext;

        if (ctx is not null)
        {
            var authorization = ctx.Request.Headers.Authorization.ToString();
            if (!string.IsNullOrEmpty(authorization))
            {
                request.Headers.TryAddWithoutValidation("Authorization", authorization);
            }

            // nginx đặt X-Real-IP từ địa chỉ thật của trình duyệt; không có thì dùng IP kết nối.
            var ip = ctx.Request.Headers["X-Real-IP"].ToString();
            if (string.IsNullOrEmpty(ip))
            {
                ip = ctx.Connection.RemoteIpAddress?.ToString() ?? "";
            }
            if (!string.IsNullOrEmpty(ip))
            {
                request.Headers.TryAddWithoutValidation("X-Real-IP", ip);
            }
        }

        return base.SendAsync(request, cancellationToken);
    }
}
