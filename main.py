import os, json, logging, asyncpg, asyncio

import discord
from discord.ext import commands
import openai


openai.api_key =        os.getenv('OPENAI_API_KEY')
TOKEN =                 os.getenv('DISCORD_TOKEN')
PG_USER =               os.getenv('PGUSER')
PG_PW =                 os.getenv('PGPASSWORD')
PG_HOST =               os.getenv('PGHOST')
PG_PORT =               os.getenv('PGPORT')
PG_DB =                 os.getenv('PGPDATABASE')


intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix='$', intents=intents)



@bot.event
async def on_ready():
    bot.pool = await asyncpg.create_pool(user=PG_USER, password=PG_PW, host=PG_HOST, port=PG_PORT, database=PG_DB, max_size=10, max_inactive_connection_lifetime=15)
    logger = logging.getLogger('discord')
    logger.setLevel(logging.DEBUG)    
    print(f'{bot.user} is connected to the following guild(s):')
        
    for guild in bot.guilds:
        print(f'{guild.name} (id: {guild.id})')



@bot.event
async def on_guild_join(guild:discord.Guild):
    banned = []
    if guild.id in banned: 
        await guild.leave()
        print(f"[X][X] Blocked {guild.name}")
        return
    
    else:
        async with bot.pool.acquire() as con:   
            await con.execute(f'''CREATE TABLE IF NOT EXISTS context (
                            
                    id              BIGINT  PRIMARY KEY NOT NULL,     
                    chatcontext     TEXT  []
                    )''')
            
            await con.execute(f'INSERT INTO context(id) VALUES({guild.id}) ON CONFLICT DO NOTHING')
		
        print(f"added to {guild}")
        


@bot.event
async def on_guild_remove(guild:discord.Guild):
    async with bot.pool.acquire() as con:
            await con.execute(f'DELETE FROM context WHERE id = {guild.id}')

    print(f"removed from {guild}")



@bot.slash_command(name="clear", description="Clear chat context.")
@commands.is_owner()
async def clear(ctx : discord.Interaction):
    await chatcontext_clear(ctx.guild.id)
    await ctx.response.send_message(f"Done. Context:```{await get_guild_x(ctx.guild.id,'chatcontext')}```", ephemeral=True)



@bot.command(name="chat", description="Chat with me.")
@commands.cooldown(1, 60, commands.BucketType.guild)  
async def chat(ctx : discord.Message, *, text):
    try:
        text = text.lower()
        author = ctx.author.display_name
        chatcontext = await get_guild_x(ctx.guild.id, "chatcontext")
        
        if not chatcontext:
            chatcontext = []
            
        
        prmpt = "You are a funny and helpful chatbot."
        messages = [{"role": "system", "content": prmpt}]      
        
        if len(chatcontext) > 0:
            if len(chatcontext) > 6:
                    if len(chatcontext) >= 500: 
                        await chatcontext_pop(ctx.guild.id, 500)         
                    									# we keep 500 in db but only use 6    
                    chatcontext = chatcontext[len(chatcontext)-6:len(chatcontext)]
            for mesg in chatcontext:   
                
                
                mesg = mesg.replace( '\\"','"').replace( "\'","'")
                mesg = mesg.split(":",1)

                if mesg[0].lower == 'bot' or mesg[0].lower == 'assistant': 
                    mesg[0] = "assistant"
                else:
                    mesg[0] = "user"
                messages.append({"role": mesg[0], "content": mesg[1]})

            messages.append({"role": "user", "content": text})
                
            

        elif not len(chatcontext) > 0:
            messages.append({"role": "user", "content": text})


        response = await openai.ChatCompletion.acreate(
            model="gpt-4",
            messages= messages,
            user = str(ctx.author.id)
    )
        await asyncio.sleep(0.1)

        
        if response["choices"][0]["finish_reason"] in ["stop","length"]:
            activity = discord.Activity(name=f"{author}", type=discord.ActivityType.listening)
            await bot.change_presence(status=discord.Status.online, activity=activity)
            
            
            message_content = response["choices"][0]["message"]["content"].strip()
            async with ctx.channel.typing():
                for i in range(0, len(message_content), 2000): 
                    if i == 0:
                        await ctx.reply(message_content[i:i+2000])
                    else:
                        await ctx.channel.send(message_content[i:i+2000])

            await chatcontext_append(ctx.guild.id, f'{author}: {text}')
            await chatcontext_append(ctx.guild.id,f'bot: {str(response["choices"][0]["message"]["content"].strip())}')
            print(f'[!chat] {ctx.guild.name} | {author}: {text}')
            print(f'{bot.user}: {str(response["choices"][0]["message"]["content"].strip())}')

        else:
            print(f'[!chat] {ctx.guild.name} | {author}: {text}')
            print(f'bot: ERROR')


    except Exception as e:
        await ctx.reply("Error")
        print(f"!chat THREW: {e}")
        


@chat.error
async def chat_error(ctx, error):
	if isinstance(error, commands.CommandOnCooldown):	
            await ctx.reply(f"Chatting too fast! {round(error.retry_after, 2)} seconds left")



async def get_guild_x(guild, x):
    try:
        async with bot.pool.acquire() as con:
            return await con.fetchval(f'SELECT {x} FROM context WHERE id = {guild}')

    except Exception as e:
        print(f'get_guild_x: {e}')
        



async def set_guild_x(guild, x, val):                                                                  
        try:
            async with bot.pool.acquire() as con:
                await con.execute(f"UPDATE context SET {x} = '{val}' WHERE id = {guild}")
            
            return await get_guild_x(guild,x)

        except Exception as e:
            print(f'set_guild_x threw {e}')
            



async def chatcontext_append(guild, what):
        what = what.replace('"', '\'\'').replace("'", "\'\'")
        async with bot.pool.acquire() as con:
            await con.execute(f"UPDATE context SET chatcontext = array_append(chatcontext, '{what}') WHERE id = {guild}")



async def chatcontext_pop(guild, what = 5):
    chatcontext = list(await get_guild_x(guild, "chatcontext"))
    
    chatcontextnew = chatcontext[len(chatcontext)-what:len(chatcontext)]
    
    await chatcontext_clear(guild)
    for mesg in chatcontextnew:
        await chatcontext_append(guild, mesg)



async def chatcontext_clear(guild):
    chatcontext = []
    async with bot.pool.acquire() as con:
        await con.execute(f"UPDATE context SET chatcontext=ARRAY{chatcontext}::text[] WHERE id = {guild}")

    return await get_guild_x(guild, "chatcontext")



bot.run(TOKEN)
