package com.dsefa.flir;
import java.util.*;
/** The graph viewport is independent of continuously acquired measurements. */
public final class GraphModel {
    public static final class Sample {public final long stamp;public final double[] values;Sample(long t,double[] v){stamp=t;values=v.clone();}}
    private final Deque<Sample> data=new ArrayDeque<>();private long window=30000,end;private boolean paused;
    public void add(long stamp,double[] values){if(!data.isEmpty()&&stamp<data.getLast().stamp)clear();data.addLast(new Sample(stamp,values));while(data.size()>60000)data.removeFirst();if(!paused)end=stamp;}
    public List<Sample> samples(){return new ArrayList<>(data);}
    public long window(){return window;}public long end(){return end;}public boolean paused(){return paused;}
    public void clear(){data.clear();end=0;paused=false;}
    public void pause(boolean b){paused=b;if(!b&&!data.isEmpty())end=data.getLast().stamp;}
    public void live(){pause(false);}
    public void zoom(double factor){if(Double.isFinite(factor)&&factor>0)window=(long)Math.max(5000,Math.min(3600000,window*factor));}
    public void pan(double fraction){if(data.isEmpty()||!Double.isFinite(fraction))return;paused=true;end=(long)Math.max(data.getFirst().stamp,Math.min(data.getLast().stamp,end+window*fraction));}
    public Sample nearest(long stamp){Sample best=null;for(Sample s:data)if(best==null||Math.abs(s.stamp-stamp)<Math.abs(best.stamp-stamp))best=s;return best;}
    public static String age(long millis){long s=Math.max(0,millis/1000);return s/3600+"h "+s%3600/60+"m "+s%60+"s ago";}
}
