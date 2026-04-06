FROM mcr.microsoft.com/dotnet/sdk:10.0 AS build
WORKDIR /src

COPY . .
RUN dotnet restore src/Vke.Web/Vke.Web.csproj
RUN dotnet build src/Vke.Web/Vke.Web.csproj -c Release -o /app

FROM mcr.microsoft.com/dotnet/aspnet:10.0
WORKDIR /app

COPY --from=build /app /app
ENV ASPNETCORE_URLS=http://+:8080
ENV ANTHROPIC_AUTH_TOKEN=${ANTHROPIC_AUTH_TOKEN}
ENV ANTHROPIC_BASE_URL=${ANTHROPIC_BASE_URL:-https://api.minimax.io/anthropic}
ENV ANTHROPIC_MODEL=${ANTHROPIC_MODEL:-MiniMax-M2.7-highspeed}
EXPOSE 8080
ENTRYPOINT ["dotnet", "Vke.Web.dll"]