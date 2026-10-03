FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src
COPY AIPlatform.Api/AIPlatform.Api.csproj AIPlatform.Api/
RUN dotnet restore AIPlatform.Api/AIPlatform.Api.csproj
COPY AIPlatform.Api/ AIPlatform.Api/
RUN dotnet publish AIPlatform.Api/AIPlatform.Api.csproj -c Release -o /out
FROM mcr.microsoft.com/dotnet/aspnet:8.0
WORKDIR /app
COPY --from=build /out .
EXPOSE 8080
ENTRYPOINT ["dotnet","AIPlatform.Api.dll"]
