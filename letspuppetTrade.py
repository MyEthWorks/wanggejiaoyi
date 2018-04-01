# -*- coding: utf-8 -*-
"""
Author: 久久为功
Date: 2017-11-19
Support multil-thread for different accounts

"""
import datetime
import pandas as pd
import sqlite3
from letspuppet import LogAll, floatdataframe
import logging
import traceback
import json
import threading
import tushare as ts
from puppet.puppet_v4 import *


def gettoday():
    return datetime.datetime.now().strftime('%Y%m%d')
    
def getweekday():
    return datetime.datetime.now().date().weekday()
    
def strprice(p):
    return '%.3f' %p
    
def getsignal(today):
    '''
    '''
    dh=sqlite3.connect(r'C:\Project\letstrade\trial_%s.db' %today)
    last2min=time.time()-90#last 1.5 mins
    try:
        signaldf=pd.read_sql("SELECT * from signal where signal.time>%f" %last2min,dh)
        signaldf=signaldf.sort_values(['code','time'],ascending=[False,False])#first trade then code then time??
        signaldf.index=signaldf['timestamp']       
    except:
        signaldf=pd.DataFrame()
    dh.close()
    return signaldf 
    
def getlimit(code,aname):
    if code[:-1]=='15900' or code=='511880' or code=='511990' or code=='131810' or code=='204001':
        return 1000000
    else:
        if aname=='a1':
            return 0#10000#0 means except money fund, no other trades are allowed
        elif aname=='a2':
            return 10000
            
def getyesterdayc(c):
    try:
        today=datetime.datetime.now().strftime('%Y-%m-%d')
        df=ts.get_k_data(c,autype=None,index=False)
        df.index=df['date']
    except:
        return -1
    if df.index[-1]==today:
        return float(df.ix[-2,'close'])
    else:
        return 0
        
def getallyesterdayc(clist):
    rt={}
    for c in clist:
        p=getyesterdayc(c)
        if p not in [0,-1]:
            rt[c]=p
    return rt
        
           
    
class alphatrade(threading.Thread):
    def __init__(self,account,name):
        threading.Thread.__init__(self)
        self.balance=0
        self.entrust=pd.DataFrame()
        self.position=pd.DataFrame()
        self.accountname=name
        self.account=account
        self.stakeholder=self.account[5]#list type
        with open('waiver.json') as f:
            self.waiverlist=json.load(f)
        self.login()
        self.updateaccount()
        
    def login(self):
        self.puppetTrade=Puppet(title='广发证券核新网上交易系统7.62')
        if not self.puppetTrade.account:
            logging.info('no account')        
        
    def getbalance(self):
        '''
        '''
        b=self.puppetTrade.balance
        s=self.puppetTrade.market_value
        self.balance=float(b)
        self.assets=float(b)+float(s)
        
        
    def getposition(self):
        p=self.puppetTrade.position
        p=pd.DataFrame(list(p))
        if p.shape[0]>0:
            p.rename(columns={'买入均价':'buy_price', '可用余额':'quant_sellable', '股票余额':'quant','证券代码':'stock_id'}, inplace = True)
            p= floatdataframe.floatdataframe(p, ['quant', 'quant_sellable', 'buy_price'])
            p.index=p['stock_id']
            p=p[p.quant>0]
            if '' in list(p.columns):
                del p['']
            self.position=p

        
    def getentrust(self):
        e=self.puppetTrade.entrustment
        e=pd.DataFrame(list(e))
        notpending=['已成','已撤','废单']
        if e.shape[0]>0:
            e.rename(columns={'委托价格':'price', '操作':'operation', '证券代码':'sid', '合同编号':'order_id'}, inplace = True)
            e= floatdataframe.floatdataframe(e, ['price'])
            e.index=e['sid']
            e=e[~e['备注'].isin(notpending)] 
            for i in range(e.shape[0]):
                if e.ix[i,'操作']=='卖出':
                    e.ix[i,'操作']='sell'
                if e.ix[i,'操作']=='买入':
                    e.ix[i,'操作']='buy'
            if '' in list(e.columns):
                del e['']
            self.entrust=e
        
    def accountinfo2db(self):
        dh=sqlite3.connect('%s.db' %self.accountname)
        dfbal=pd.DataFrame({self.accountname:pd.Series({'balance':self.balance})})
        dfbal.to_sql('balance',dh,if_exists='replace',index=True)
        if self.position.shape[0]>0:
            self.position.to_sql('position',dh,if_exists='replace',index=False)
        if self.entrust.shape[0]>0:
            self.entrust.to_sql('entrust',dh,if_exists='replace',index=False)
        dh.close()
        
    def updateaccount(self):
        self.puppetTrade.refresh()
        self.getbalance()
        logging.info([self.balance,self.assets])
        self.getentrust()
        self.getposition()
        logging.info(self.position)
        logging.info(self.entrust)
        try:
            self.accountinfo2db()
        except:
            logging.info(traceback.print_exc())

        
    def bid(self,code,m,p):
        if m<8000:#avoid bid in too frequently
            m=0
        if code[:4]=='1318':
            qty=m//1000*10
            if qty>0:
                limit=code,strprice(p),str(int(qty))
                self.puppetTrade.sell(*limit)
                self.updateaccount()
        else:
            qty=m/p//100*100
            if qty>0:
                logging.info('bid qty is %d,p is %f' %(qty,p))
                limit=code,strprice(p),str(int(qty))
                self.puppetTrade.buy(*limit)
                self.updateaccount()

    def ask(self,code,p,q):
        limit=code,strprice(p),str(int(q))
        self.puppetTrade.sell(*limit)
        self.updateaccount()

    def cancelorder(self,t):
        if t=='buy':
            self.puppetTrade.cancel_buy()
        if t=='sell':
            self.puppetTrade.cancel_sell()
        self.updateaccount()
        
        
    def run(self):     
        #marketStart=datetime.time(9,30,0,0)
        marketEnd=datetime.time(14,59,0,0)
        noonStart=datetime.time(11,27,0,0)
        noonEnd=datetime.time(13,2,0,0)
        now=datetime.datetime.now().time()
        today=gettoday()
        if not (now<=marketEnd and getweekday()<5):
            print('logout 1 done')
            self.logout()
            return 1
        roundcnt=0 
        self.t=time.time()
        self.yesterdaycp={}
        bcheckycp=True        
        while now<=marketEnd and getweekday()<5:
            now=datetime.datetime.now().time()
            if noonStart<now<noonEnd:
                time.sleep(10)
                continue
            if now>datetime.time(9,32,0,0) and bcheckycp:
                try:
                    self.yesterdaycp=getallyesterdayc(list(self.position['stock_id']))
                    if len(self.yesterdaycp)==self.position.shape[0]:
                        logging.info(self.yesterdaycp)
                        bcheckycp=False
                except:
                    print('fail get yesterday close')
            if time.time()-self.t>240:               
                self.updateaccount()
                self.t=time.time()
            self.signaldf=getsignal(today)
            if self.signaldf.shape[0]>0:
                self.signaldf=self.signaldf[self.signaldf['index'].isin(self.account[4])]
            try:
                self.__loopsignal()
                self.__loopentrust()
            except:
                time.sleep(3.5)
                logging.info(traceback.print_exc())
                self.updateaccount()
            roundcnt+=1
            logging.info('round id: %d' %roundcnt)        
            time.sleep(3.5)
        time.sleep(150)
        self.updateaccount()
        self.logout()
        with open('balance_%s.txt' %self.accountname,mode='a') as f:
            f.write(self.accountname+','+gettoday()+','+str(self.assets)+'\n')
        logging.info('logout done')
        
    def __loopsignal(self):
        for i in range(self.signaldf.shape[0]):
            if i>0 and self.signaldf.ix[i,'code']==self.signaldf.ix[i-1,'code'] and self.signaldf.ix[i,'trade']==self.signaldf.ix[i-1,'trade']:
                continue
            #logging.info(self.signaldf.ix[i])  
            if self.signaldf.ix[i,'trade']=='bid':#buy
                bbid1=bbid2=False
                if self.entrust.shape[0]==0:
                    bbid1=True#no enturst
                else:
                    bentrust=self.entrust[self.entrust.operation=='buy']
                    bbid1=self.signaldf.ix[i,'code'] not in list(bentrust['sid'])
                if self.position.shape[0]==0:
                    bbid2=True#no position
                else:
                    #bbid2=self.signaldf.ix[i,'code'] not in list(self.position['stock_id']) 
                    if self.signaldf.ix[i,'code'] in list(self.position['stock_id']):
                        qty=self.position['quant'][self.signaldf.ix[i,'code']]
                        bbid2=qty*self.signaldf.ix[i,'price']<getlimit(self.signaldf.ix[i,'code'],self.accountname)*0.5
                    else:
                        bbid2=True
                if  bbid1 and bbid2:
                    limit=getlimit(self.signaldf.ix[i,'code'],self.accountname)
                    if self.balance<limit:
                        m=self.balance
                    else:
                        m=limit
                    self.bid(self.signaldf.ix[i,'code'],m,self.signaldf.ix[i,'price'])
                    logging.info('bid done %s' %(self.signaldf.ix[i,'code']))
            elif self.signaldf.ix[i,'trade']=='ask':#sell
                bask1=bask2=False
                if self.entrust.shape[0]==0:
                    bask1=True
                else:
                    aentrust=self.entrust[self.entrust.operation=='sell']
                    bask1=self.signaldf.ix[i,'code'] not in list(aentrust['sid'])
                if self.position.shape[0]!=0:
                    avlposition=self.position[self.position.quant_sellable>0]
                    bask2=self.signaldf.ix[i,'code'] in list(avlposition['stock_id'])
                btmp=self.signaldf.ix[i,'code'] not in self.waiverlist
                if self.signaldf.ix[i,'code'] in self.position.index:
                    bskip=btmp and self.position['buy_price'][self.signaldf.ix[i,'code']]>self.signaldf.ix[i,'price']
#                    if self.signaldf.ix[i,'code'] in self.yesterdaycp:
#                        bskip=bskip and self.yesterdaycp[self.signaldf.ix[i,'code']]>self.signaldf.ix[i,'price']
                    if bskip:
                        continue
                else:
                    continue
                if  bask1 and bask2:
                    avlqty=int(self.position['quant_sellable'][self.signaldf.ix[i,'code']])
                    self.ask(self.signaldf.ix[i,'code'],self.signaldf.ix[i,'price'],avlqty)
                    logging.info('ask done %s' %(self.signaldf.ix[i,'code']))
                    
            time.sleep(0.2)
    def __loopentrust(self):
        for j in range(self.entrust.shape[0]):
            if self.entrust.ix[j,'operation']=='sell':
                opr='ask'
            elif self.entrust.ix[j,'operation']=='buy':
                opr='bid'
            else:
                opr='na'
            bcancel=False
            if self.signaldf.shape[0]==0:
                bcancel=True
            else:
                sametrade=self.signaldf[(self.signaldf['code']==self.entrust.ix[j,'sid']) & (self.signaldf['trade']==opr)]
                if sametrade.shape[0]==0:
                    bcancel=True
                else:
                    bcancel=strprice(sametrade.ix[0,'price'])!=strprice(float(self.entrust.ix[j,'price']))
                    logging.info([strprice(sametrade.ix[0,'price']),strprice(float(self.entrust.ix[j,'price']))])
            if bcancel:#:
                print(self.entrust.ix[j])
                self.cancelorder(self.entrust.ix[j,'operation'])
                logging.info('cancel entrust done')
            time.sleep(0.5)        
        
            
    def logout(self):
        pass

         
@LogAll('Tp')
def main():
    time.sleep(2)#wait for exe start up
    logging.basicConfig(level=logging.INFO,
                format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(funcName)s %(message)s',
                datefmt='%a, %d %b %Y %H:%M:%S')#CRITICAL > ERROR > WARNING > INFO > DEBUG > NOTSET
    with open('accounts.json') as f:
        accounts=json.load(f)
    threadlist=[]
    for k,v in accounts.items():
        threadlist.append(alphatrade(v,k))
        threadlist[-1].start()
    for t in threadlist:
        t.join()

            
if __name__=='__main__': 
    main()



